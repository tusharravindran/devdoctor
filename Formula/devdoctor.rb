class Devdoctor < Formula
  include Language::Python::Virtualenv

  desc "Real-time log diagnostics CLI for backend developers"
  homepage "https://github.com/tusharravindran/devdoctor"
  url "https://github.com/tusharravindran/devdoctor/archive/refs/tags/v1.0.7.tar.gz"
  sha256 "5d79b2e8a3834198534a16aa912781e153dd322ade07760104c01153e9a81394"
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "devdoctor 1.0.7", shell_output("#{bin}/devdoctor --version")
    assert_match "run", shell_output("#{bin}/devdoctor --help")
    assert_match "watch", shell_output("#{bin}/devdoctor --help")
  end
end
