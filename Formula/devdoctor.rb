class Devdoctor < Formula
  include Language::Python::Virtualenv

  desc "Backend log diagnostics CLI"
  homepage "https://github.com/<user>/devdoctor"
  url "https://github.com/<user>/devdoctor/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "<SHA256>"
  license "MIT"

  depends_on "python@3.11"

  # Required for Python < 3.11 (TOML parser)
  resource "tomli" do
    url "https://files.pythonhosted.org/packages/source/t/tomli/tomli-2.0.1.tar.gz"
    sha256 "de526c12914f0c550d15924c62d72abc48d6fe7364aa87328337a31007fe8a4f"
  end

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/devdoctor", "--help"
  end
end
