class Devdoctor < Formula
  include Language::Python::Virtualenv

  desc "Real-time log diagnostics CLI for backend developers"
  homepage "https://github.com/tusharravindran/devdoctor"
  url "https://github.com/tusharravindran/devdoctor/archive/refs/tags/v1.0.2.tar.gz"
  sha256 "d37257edd7d64447c524fce30b67cdfa6808a06d9320d89f4f987ed6a7998258"
  license "MIT"

  # python@3.13 has pre-built bottles for all current macOS versions.
  # tomllib is stdlib on 3.11+ so no extra dependency needed.
  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "devdoctor 1.0.2", shell_output("#{bin}/devdoctor --version")
    assert_match "run", shell_output("#{bin}/devdoctor --help")
    assert_match "watch", shell_output("#{bin}/devdoctor --help")
  end
end
