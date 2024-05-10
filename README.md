# TMDFlakeFinder
Automation script for identifying TMD flakes.

It was used for the following publication: 

## Attribution
If the code is used in any way, the publication must be cited. 

## License

Shield: [![CC BY-NC-SA 4.0][cc-by-nc-sa-shield]][cc-by-nc-sa]

This work is licensed under a
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License][cc-by-nc-sa].

[![CC BY-NC-SA 4.0][cc-by-nc-sa-image]][cc-by-nc-sa]

[cc-by-nc-sa]: http://creativecommons.org/licenses/by-nc-sa/4.0/
[cc-by-nc-sa-image]: https://licensebuttons.net/l/by-nc-sa/4.0/88x31.png
[cc-by-nc-sa-shield]: https://img.shields.io/badge/License-CC%20BY--NC--SA%204.0-lightgrey.svg

## Getting Started

1. Install Python (Version: 3.10.7) for Windows (https://www.python.org/downloads/windows/)
2. Install Spyder for Windows
(https://docs.spyder-ide.org/current/installation.html#standalone-installers-ref)
3. To create a virtual environment (venv), open PowerShell and navigate to the desired path
where the venv is to be located:
cd - change directory
4. Execute the following command to create the venv:
py(thon) -m venv [venv_name]
5. Change the Python interpreter on Spyder via Tools -> Preferences -> Python interpreter
and provide the path of the newly created venv.
6. Navigate to the directory where the venv lies before activating it.
7. Activate venv (with PowerShell) with:
[venv_name]
8. One might also need to run the following:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned
and confirm with ’Y’
9. Install all required packages in the venv with the requirements.txt file:
pip install -r requirements.txt
10. Restart Spyder to apply the changes after setting up the venv and its packages.
