import os
import shutil
import zipapp

source_dir = "."
temp_dir = "./temp"
output_file = "PriceMonitor.pyz"

excluded_dirs = [
    '.idea',
    '.venv',
    '.git',
    'logs',
]

excluded_files = [
    '.gitignore',
    '.python-version',
    'PriceMonitor.iml',
    'PriceMonitor.sqlite',
    'PriceMonitor.iml',
    'pyproject.toml',
    'uv.lock',
    'build.by',
    output_file
]
def exclude_dir(dirs, name):
    if name in dirs:
        dirs.remove(name)

# Create a temporary directory and copy only desired files
if os.path.exists(temp_dir):
    shutil.rmtree(temp_dir)
os.makedirs(temp_dir)

# Example: Copy all .py files and a specific data directory
for root, dirs, files in os.walk(source_dir):
    relative_path = os.path.relpath(root, source_dir)
    target_root = os.path.join(temp_dir, relative_path)
    os.makedirs(target_root, exist_ok=True)

    for file in files:
        if file.endswith(".py") and not file in excluded_files: # Exclude specific file
            shutil.copy2(os.path.join(root, file), target_root)

    for dir in excluded_dirs:
        exclude_dir(dirs, dir)

if __name__ == '__main__':
    # Create the zipapp from the temporary directory
    zipapp.create_archive(temp_dir, target=output_file)

    # Clean up the temporary directory
    shutil.rmtree(temp_dir)