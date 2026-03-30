"""Autofix planning and safe auto-apply helpers."""

from __future__ import annotations

import difflib
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .utils import color

AUTO_APPLY_RULES = {"bullet_remove_exact_hint", "port_collision_bump"}
SEARCHABLE_SUFFIXES = {".rb", ".rake", ".builder", ".jbuilder", ".erb", ".py", ".js", ".cjs", ".mjs", ".go"}
SEARCHABLE_DIRS = ("app", "lib", "config")


class AutofixManager:
    """Apply a narrow set of low-risk autofixes during a live session."""

    def __init__(self, mode: str, issue_tracker, request_tracker=None) -> None:
        self._mode = mode
        self._issue_tracker = issue_tracker
        self._request_tracker = request_tracker
        self._project_root = Path.cwd()
        self._completed_fingerprints = set()
        self._attempt_signatures: Dict[str, Tuple[int, int]] = {}

    def process_pending(self, html_writer=None, force: bool = False) -> None:
        if self._mode != "apply":
            return

        should_refresh = False

        for issue in self._issue_tracker.autofix_issues():
            fingerprint = str(issue.get("fingerprint") or "")
            if not fingerprint or fingerprint in self._completed_fingerprints:
                continue

            signature = self._issue_signature(issue)
            if not force and self._attempt_signatures.get(fingerprint) == signature:
                continue
            self._attempt_signatures[fingerprint] = signature

            current_plan = dict(issue.get("autofix") or {})
            plan = self._prepare_plan(issue)
            if plan != current_plan:
                self._issue_tracker.update_autofix_plan(fingerprint, plan)
                should_refresh = True

            plan_status = str(plan.get("status") or "")
            if not plan.get("auto_apply") or plan_status != "available":
                continue

            rule_id = str(plan.get("rule_id") or "")
            if rule_id not in AUTO_APPLY_RULES:
                self._completed_fingerprints.add(fingerprint)
                self._issue_tracker.mark_autofix_result(
                    fingerprint,
                    {
                        "status": "failed",
                        "reason": f"Rule {rule_id} is not allowed in auto-apply mode.",
                    },
                )
                print(
                    color.warn(
                        f'Autofix failed -> {issue["title"]}: '
                        f"Rule {rule_id} is not allowed in auto-apply mode."
                    ),
                    flush=True,
                )
                should_refresh = True
                continue

            print(
                color.info(
                    f'Autofix applying -> {plan.get("summary", issue["title"])}'
                ),
                flush=True,
            )
            result = self._apply_plan(plan)
            self._issue_tracker.mark_autofix_result(fingerprint, result)
            self._completed_fingerprints.add(fingerprint)
            should_refresh = True

            if result.get("status") == "applied":
                print(
                    color.success(
                        f'Autofix applied -> {result.get("summary", issue["title"])}'
                    ),
                    flush=True,
                )
            else:
                print(
                    color.warn(
                        f'Autofix failed -> {issue["title"]}: '
                        f'{result.get("reason", issue["title"])}'
                    ),
                    flush=True,
                )

        if should_refresh and html_writer is not None:
            html_writer.refresh()

    def finalize(self) -> None:
        if self._mode != "apply":
            return

        self.process_pending(force=True)

        issues = self._issue_tracker.autofix_issues()
        applied = 0
        failed = 0
        unavailable = 0

        for issue in issues:
            autofix = dict(issue.get("autofix") or {})
            status = str(autofix.get("status") or "")
            if status == "applied":
                applied += 1
                continue
            if status == "failed":
                failed += 1
                continue
            if status == "unavailable":
                unavailable += 1
                print(
                    color.warn(
                        f'Autofix unavailable -> {issue["title"]}: '
                        f'{autofix.get("reason", "No safe patch plan was available.")}'
                    ),
                    flush=True,
                )

        if applied or failed or unavailable:
            print(
                color.info(
                    f"Autofix summary: {applied} applied, {failed} failed, {unavailable} unavailable"
                ),
                flush=True,
            )
        else:
            print(
                color.info("Autofix summary: no eligible auto-apply rules matched this session."),
                flush=True,
            )

    def _issue_signature(self, issue: Dict[str, Any]) -> Tuple[int, int]:
        request_id = str(
            (issue.get("latest_example") or {}).get("request_id")
            or (issue.get("autofix") or {}).get("request_id")
            or ""
        ).strip()
        trace_length = 0
        if request_id and self._request_tracker is not None:
            trace = self._request_tracker.get_trace(request_id) or {}
            trace_length = len(trace.get("lines") or [])
        return int(issue.get("count") or 0), trace_length

    def _prepare_plan(self, issue: Dict[str, Any]) -> Dict[str, Any]:
        plan = dict(issue.get("autofix") or {})
        rule_id = str(plan.get("rule_id") or "")
        if rule_id != "bullet_remove_exact_hint":
            return plan

        search = str(plan.get("search") or "")
        if not search:
            return {
                **plan,
                "status": "unavailable",
                "auto_apply": False,
                "reason": "The autofix plan did not include an exact eager-loading snippet to remove.",
            }

        candidates = self._candidate_paths(issue, plan)
        exact_match = self._select_exact_match(candidates, search, plan)
        if exact_match is not None:
            return exact_match

        global_match = self._search_project(search, plan, preferred_paths=candidates)
        if global_match is not None:
            return global_match

        searched = ", ".join(str(path) for path in candidates[:4])
        reason = (
            "devdoctor could not locate a single unambiguous source line for this eager-loading hint. "
            "It searched callstack, controller, model, and project files."
        )
        if searched:
            reason += f" Checked: {searched}"
        return {
            **plan,
            "status": "unavailable",
            "auto_apply": False,
            "reason": reason,
        }

    def _candidate_paths(self, issue: Dict[str, Any], plan: Dict[str, Any]) -> List[Path]:
        paths: List[Path] = []
        self._add_candidate(paths, plan.get("file"))

        for frame in plan.get("callstack") or []:
            self._add_candidate(paths, self._frame_to_path(frame))

        latest = issue.get("latest_example") or {}
        table = str(plan.get("table") or latest.get("table") or "").strip()
        request_id = str(plan.get("request_id") or latest.get("request_id") or "").strip()
        request_trace = self._request_tracker.get_trace(request_id) if request_id and self._request_tracker else None

        if request_trace:
            controller_path = self._controller_file(request_trace.get("controller"))
            self._add_candidate(paths, controller_path)
            if controller_path is not None:
                plan["request_controller_file"] = str(controller_path.resolve())
            action = str(request_trace.get("action") or "").strip()
            if action:
                plan["request_action"] = action
            controller = str(request_trace.get("controller") or "").strip()
            if controller:
                plan["request_controller"] = controller

        self._add_candidate(paths, self._model_file(table))
        return paths

    def _add_candidate(self, paths: List[Path], candidate: Any) -> None:
        if not candidate:
            return
        path = Path(str(candidate)).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved in paths:
            return
        paths.append(resolved)

    def _frame_to_path(self, frame: Any) -> Optional[Path]:
        raw = str(frame or "").strip()
        if not raw:
            return None

        path_part = raw.split(":", 1)[0]
        candidate = Path(path_part)
        if candidate.is_file():
            return candidate.resolve()

        project_candidate = (self._project_root / path_part).resolve()
        if project_candidate.is_file():
            return project_candidate
        return None

    def _controller_file(self, controller_name: Any) -> Optional[Path]:
        raw = str(controller_name or "").strip()
        if not raw:
            return None

        parts = [part for part in raw.split("::") if part]
        if not parts:
            return None

        path_parts = [self._camel_to_snake(part) for part in parts]
        if not path_parts[-1].endswith("_controller"):
            path_parts[-1] = f"{path_parts[-1]}_controller"
        candidate = self._project_root / "app" / "controllers" / Path(*path_parts)
        return candidate.with_suffix(".rb")

    def _model_file(self, table: str) -> Optional[Path]:
        if not table:
            return None
        candidate = self._project_root / "app" / "models" / f"{self._camel_to_snake(table)}.rb"
        return candidate

    def _camel_to_snake(self, value: str) -> str:
        text = value.replace("::", "/")
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", text)
        text = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", text)
        return text.replace("-", "_").lower()

    def _select_exact_match(
        self,
        candidates: Iterable[Path],
        search: str,
        plan: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        for path in candidates:
            match = self._match_in_file(path, search, plan)
            if match is not None:
                matches.append(match)

        if len(matches) == 1:
            return matches[0]

        controller_path = str(plan.get("request_controller_file") or "")
        if controller_path:
            for match in matches:
                if match.get("file") == controller_path:
                    return match

        return None

    def _search_project(
        self,
        search: str,
        plan: Dict[str, Any],
        preferred_paths: Iterable[Path],
    ) -> Optional[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        preferred = {str(path) for path in preferred_paths if path}

        for root_name in SEARCHABLE_DIRS:
            root = self._project_root / root_name
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in SEARCHABLE_SUFFIXES and path.name.lower() not in {"rakefile"}:
                    continue
                match = self._match_in_file(path, search, plan)
                if match is not None:
                    matches.append(match)

        preferred_matches = [match for match in matches if match.get("file") in preferred]
        if len(preferred_matches) == 1:
            return preferred_matches[0]
        if len(matches) == 1:
            return matches[0]
        return None

    def _match_in_file(
        self,
        path: Path,
        search: str,
        plan: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        if not path.is_file():
            return None

        try:
            source = path.read_text(encoding="utf-8")
        except OSError:
            return None

        match_count = source.count(search)
        if match_count != 1:
            return None

        updated = source.replace(search, str(plan.get("replacement") or ""), 1)
        target = str(plan.get("target") or "this query path")
        return {
            **plan,
            "status": "available",
            "auto_apply": True,
            "file": str(path.resolve()),
            "summary": f"Remove {search} from {path.name} for {target}.",
            "patch_preview": self._build_patch_preview(path, source, updated),
        }

    def _build_patch_preview(self, path: Path, before: str, after: str) -> str:
        diff = difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=str(path),
            tofile=str(path),
            lineterm="",
        )
        return "\n".join(diff)

    def _apply_plan(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        rule_id = str(plan.get("rule_id") or "")
        if rule_id in {"bullet_remove_exact_hint", "port_collision_bump"}:
            return self._apply_literal_replace(plan)
        return {
            "status": "failed",
            "reason": f"No apply handler exists for rule {rule_id}.",
        }

    def _apply_literal_replace(self, plan: Dict[str, Any]) -> Dict[str, Any]:
        file_value = str(plan.get("file") or "").strip()
        search = str(plan.get("search") or "")
        replacement = str(plan.get("replacement") or "")
        if not file_value or not search:
            return {
                "status": "failed",
                "reason": "The autofix plan is missing its target file or search snippet.",
            }
        file_path = Path(file_value)

        try:
            source = file_path.read_text(encoding="utf-8")
        except OSError as exc:
            return {
                "status": "failed",
                "file": str(file_path),
                "reason": f"Could not read {file_path.name}: {exc}",
            }

        match_count = source.count(search)
        if match_count != 1:
            return {
                "status": "failed",
                "file": str(file_path),
                "reason": (
                    f"Found {match_count} exact matches for {search} in {file_path.name}; "
                    "apply mode requires exactly one."
                ),
            }

        updated = source.replace(search, replacement, 1)
        if updated == source:
            return {
                "status": "failed",
                "file": str(file_path),
                "reason": f"{file_path.name} did not change after applying the planned replacement.",
            }

        try:
            file_path.write_text(updated, encoding="utf-8")
        except OSError as exc:
            return {
                "status": "failed",
                "file": str(file_path),
                "reason": f"Could not write {file_path.name}: {exc}",
            }

        verification = self._verify_file(file_path)
        if verification.get("status") == "failed":
            try:
                file_path.write_text(source, encoding="utf-8")
            except OSError as exc:
                verification["reason"] = (
                    f'{verification.get("reason", "Verification failed.")} '
                    f'Also failed to restore {file_path.name}: {exc}'
                )
            return {
                "status": "failed",
                "file": str(file_path),
                "summary": plan.get("summary")
                or f"Updated {file_path.name} with the planned autofix.",
                "verification_status": verification.get("status"),
                "verification_cmd": verification.get("command"),
                "verification_output": verification.get("output"),
                "reason": verification.get("reason")
                or f"{file_path.name} failed syntax verification after patching.",
            }

        return {
            "status": "applied",
            "file": str(file_path),
            "applied_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "summary": plan.get("summary")
            or f"Updated {file_path.name} with the planned autofix.",
            "verification_status": verification.get("status"),
            "verification_cmd": verification.get("command"),
            "verification_output": verification.get("output"),
        }

    def _verify_file(self, file_path: Path) -> Dict[str, Any]:
        command = self._verification_command(file_path)
        if not command:
            return {
                "status": "unavailable",
                "reason": f"No built-in verifier exists for {file_path.suffix or file_path.name}.",
            }

        try:
            proc = subprocess.run(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return {
                "status": "unavailable",
                "command": " ".join(command),
                "reason": f"{command[0]} is not available to verify {file_path.name}.",
            }

        output = (proc.stdout or "").strip()
        if proc.returncode != 0:
            return {
                "status": "failed",
                "command": " ".join(command),
                "output": output,
                "reason": output or f"{file_path.name} failed syntax verification.",
            }

        return {
            "status": "passed",
            "command": " ".join(command),
            "output": output,
        }

    def _verification_command(self, file_path: Path) -> List[str]:
        suffix = file_path.suffix.lower()
        name = file_path.name.lower()
        if suffix in {".rb", ".ru", ".builder", ".jbuilder"} or name.endswith(".rake"):
            return ["ruby", "-c", str(file_path)]
        if suffix == ".py":
            return ["python3", "-m", "py_compile", str(file_path)]
        if suffix in {".js", ".cjs", ".mjs"}:
            return ["node", "--check", str(file_path)]
        if suffix == ".go":
            return ["gofmt", "-w", str(file_path)]
        return []
