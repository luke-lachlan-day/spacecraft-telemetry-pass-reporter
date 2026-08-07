Spacecraft Telemetry Pass Reporter - Windows x64
================================================

Run "Telemetry Reporter.exe" from this folder. Keep the _internal folder beside
the executable and keep "Telemetry Reporter.exe.config" beside it; all three are
required. No Python installation or network connection is needed.

The application requires Microsoft Edge WebView2 Runtime. Current Windows 10 and
Windows 11 installations normally include it. If it is missing, the application
offers to open Microsoft's official download page.

This portable build is unsigned. Windows SmartScreen may therefore show an
unrecognized-app warning. Verify the downloaded ZIP against its published
SHA-256 checksum before choosing to run it.

If Windows reports that Python.Runtime.Loader.Initialize could not be resolved,
verify the checksum again. As a fallback, unblock the original ZIP from its
Properties window and extract a fresh copy. Normal Explorer extraction should
not require this workaround.

The bundled examples and generated reports contain fictional demonstration data.
This software is not intended for mission use.

Project and source: https://github.com/luke-lachlan-day/spacecraft-telemetry-pass-reporter
License: MIT (see LICENSE)
