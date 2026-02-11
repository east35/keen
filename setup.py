"""
py2app setup script for Kindle Send menu bar app.
Build with: python setup.py py2app
"""

from setuptools import setup

APP = ['kindle_menubar.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'Kindle Send',
        'CFBundleDisplayName': 'Kindle Send',
        'CFBundleIdentifier': 'com.kindlesend.app',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSUIElement': True,  # Hide from Dock, menu bar only
        'LSEnvironment': {
            'KINDLE_EMAIL': '',
            'SMTP_EMAIL': '',
            'SMTP_PASSWORD': '',
        },
    },
    'packages': ['rumps', 'bs4', 'requests', 'certifi'],
    'includes': ['AppKit'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
