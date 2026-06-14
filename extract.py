import ast
import os
import re

files_to_check = ['gui.py', 'widgets.py', 'workers.py']

strings = set()

for file in files_to_check:
    with open(file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Simple regex to find strings used in common GUI calls like QPushButton("...", QLabel("...")
    matches = re.findall(r'(?:QPushButton|QLabel|QGroupBox|setWindowTitle|setText|QMessageBox\.(?:warning|information|critical|question).*?|addTab|QAction|QListWidgetItem|QCheckBox)\s*\(\s*(["\'])(.*?)\1', content)
    for quote, text in matches:
        if text and not text.startswith("QListWidget") and not text.startswith("QProgressBar"):
            strings.add(text)
            
    matches2 = re.findall(r'(?:setText|setTitle|setInformativeText|setWindowTitle)\s*\(\s*(["\'])(.*?)\1', content)
    for quote, text in matches2:
        strings.add(text)

print("Found strings:")
for s in sorted(strings):
    print(f'"{s}",')

