# devdoctor apt repo

This branch hosts the unsigned third-party APT feed for devdoctor releases.

Install:

    echo "deb [trusted=yes] https://raw.githubusercontent.com/tusharravindran/devdoctor/apt stable main" | sudo tee /etc/apt/sources.list.d/devdoctor.list
    sudo apt update
    sudo apt install devdoctor
