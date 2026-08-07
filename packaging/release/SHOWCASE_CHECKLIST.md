# Windows Release Showcase Checklist

Complete this checklist using the downloaded release assets on a clean Windows account or a second
Windows 10/11 x64 machine. Do not use a repository build. Record the tested tag, ZIP SHA-256,
Windows version, WebView2 version, date, and tester with the release evidence.

## Download and startup

- [ ] Download the versioned ZIP, `.sha256`, and build-information assets from the same release
      using a web browser.
- [ ] Calculate the ZIP SHA-256 and confirm it exactly matches the published checksum.
- [ ] Confirm the build-information tag and commit are the intended release source.
- [ ] Without selecting **Unblock** in the ZIP Properties window, extract the entire ZIP using
      Windows Explorer.
- [ ] Keep `Telemetry Reporter.exe` beside `_internal`, `Telemetry Reporter.exe.config`, `LICENSE`,
      `README.txt`, and `BUILD-INFO.txt`.
- [ ] Double-click `Telemetry Reporter.exe` and confirm it reaches the Quick Experiment without a
      `Python.Runtime.Loader.Initialize` or managed-assembly loading error.
- [ ] Confirm the unsigned-app/SmartScreen message is understandable after checksum verification.
- [ ] Confirm the missing-WebView2 guidance is understandable, or record the installed runtime
      version when the application opens normally.
- [ ] Close the application and confirm neither `debug.log` nor `chromium.log` was created beside
      the executable or in the directory used to launch it.

## Quick Experiment boundaries

Analyze each exact boundary and confirm the overall and battery/temperature/signal labels are
produced by the Python analysis result:

- [ ] Nominal defaults: `3.80 V`, `25.0 °C`, `-80 dBm`.
- [ ] Battery nominal side `3.61 V`, warning boundary `3.60 V`, and critical boundary `3.40 V`.
- [ ] Temperature nominal side `39.9 °C`, warning boundary `40.0 °C`, and critical boundary
      `50.0 °C`.
- [ ] Signal nominal side `-89 dBm`, warning boundary `-90 dBm`, and critical boundary `-105 dBm`.
- [ ] Immediately edit a value after analysis and confirm the result, preview, and save availability
      disappear until analysis is run again.

## Full editor and native dialogs

- [ ] Load both bundled examples and confirm the editor and analysis result update.
- [ ] Import a valid JSON pass and analyze it.
- [ ] Save normalized JSON, reopen it, and confirm its contents identify the analyzed pass.
- [ ] Save the HTML report and open it in a browser; confirm it is self-contained and readable.
- [ ] Analyze a full pass, cancel the import dialog, and confirm the editor, existing result, and
      preview remain unchanged; then save both the normalized JSON and HTML report without
      reanalyzing.
- [ ] Cancel both save dialogs and confirm the application remains usable with no error.

## Release decision

- [ ] Confirm the matching Windows Release workflow completed successfully and its final publication
      step created the public release only after validation, packaged tests, checksum creation, and
      workflow-artifact upload succeeded.
- [ ] Confirm the release contains the versioned ZIP, checksum, and build-information assets.
- [ ] Record all results and retain any screenshots or failing input needed to reproduce an issue.
- [ ] If any required check fails, do not replace the published assets. Fix forward with the next
      patch version.
