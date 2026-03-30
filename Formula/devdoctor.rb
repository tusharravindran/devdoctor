class Devdoctor < Formula
  include Language::Python::Virtualenv

  desc "Real-time log diagnostics CLI for backend developers"
  homepage "https://github.com/tusharravindran/devdoctor"
  url "https://github.com/tusharravindran/devdoctor/archive/refs/tags/v1.0.3.tar.gz"
  sha256 "2e40a084852bc9ad541378ae1601a0681ae0ccc7e6cb1a07eb60cb60f8e084a7"
  license "MIT"

  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "devdoctor 1.0.3", shell_output("#{bin}/devdoctor --version")
    assert_match "run", shell_output("#{bin}/devdoctor --help")
    assert_match "watch", shell_output("#{bin}/devdoctor --help")
  end
end
