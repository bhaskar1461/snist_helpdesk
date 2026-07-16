# Contributing Guidelines

Thank you for choosing to contribute to the SNIST Helpdesk! We appreciate your support.

## Code of Conduct

By participating, you agree to uphold our [Code of Conduct](CODE_OF_CONDUCT.md).

## How Can I Contribute?

### Reporting Bugs
- Search existing issues to verify the bug has not already been reported.
- Open a new issue with a clear title, description, and steps to reproduce.
- Include logs and screenshots if relevant.

### Suggesting Enhancements
- Open a new issue outlining the feature request.
- Describe the use-case and why this enhancement is valuable to the community.

### Pull Requests
1. Fork the repository and create your branch from `main`.
2. Install local development dependencies and set up the virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate # On Windows
   source .venv/bin/activate # On Unix/macOS
   pip install -r requirements.txt
   ```
3. Verify that your changes pass all unit tests:
   ```bash
   python -m unittest discover -s tests/
   ```
4. Format your changes and write clear commit messages.
5. Submit a pull request targeting the `main` branch.
