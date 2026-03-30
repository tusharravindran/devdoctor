class Devdoctor < Formula
  include Language::Python::Virtualenv

  desc "Real-time log diagnostics CLI for backend developers"
  homepage "https://github.com/tusharravindran/devdoctor"
  url "https://github.com/tusharravindran/devdoctor/archive/refs/tags/v1.0.2.tar.gz"
  sha256 "d37257edd7d64447c524fce30b67cdfa6808a06d9320d89f4f987ed6a7998258"
  license "MIT"

  depends_on "python@3.11"

  # Required only on Python < 3.11 (tomllib is stdlib on 3.11+)
  resource "tomli" do
    url "https://files.pythonhosted.org/packages/source/t/tomli/tomli-2.0.1.tar.gz"
    sha256 "de526c12914f0c550d15924c62d72abc48d6fe7364aa87328337a31007fe8a4f"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "devdoctor 1.0.2", shell_output("#{bin}/devdoctor --version")
    assert_match "run", shell_output("#{bin}/devdoctor --help")
    assert_match "watch", shell_output("#{bin}/devdoctor --help")
  end
end
