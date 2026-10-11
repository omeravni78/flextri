---
layout: default
title: Install
---
# Install flexTri

flexTri is a small app that runs on your own computer and opens in your web browser. You don't need to install Python or anything else.

<a class="btn" href="https://github.com/omeravni78/flextri/releases/latest">Go to the download page</a>

On the download page, look under **Assets** and pick the file for your computer:

<div class="table-wrap" markdown="1">

| Your computer | File to download |
| --- | --- |
| Windows 10 or 11 | `flexTri-…-windows-setup.exe` |
| Mac with Apple chip (M1 or newer) | `flexTri-…-macos-apple-silicon.dmg` |
| Older Mac with Intel chip | `flexTri-…-macos-intel.dmg` |
| Linux | `flexTri-…-linux-x86_64.AppImage` |

</div>

<div class="note"><p><strong>Your computer will warn you the first time.</strong> flexTri is not yet signed with a paid developer certificate, so Windows and macOS don't recognise it. The steps below show how to open it anyway. This is only needed once.</p></div>

## Windows

1. Double-click the `windows-setup.exe` file you downloaded.
2. If Windows says **"Windows protected your PC"**, click **More info**, then **Run anyway**.
3. Click through the installer. flexTri opens in your browser when it finishes.
4. Next time, start it from the Start menu or the desktop icon.

## Mac

1. Open the `.dmg` file and drag **flexTri** onto **Applications**.
2. Open flexTri from Applications. The first time, macOS blocks it.
3. Open **System Settings → Privacy & Security**, scroll down and click **Open Anyway**. Then open flexTri again.

## Linux

1. Right-click the `.AppImage` file, choose **Properties**, and allow running it as a program (or run `chmod +x` on it).
2. Double-click it.

## Once it's running

flexTri opens a tab in your browser at `http://127.0.0.1:8000`. That address means "this computer": nothing is sent to a flexTri server, because there isn't one.

The first time, you land on the setup. [Here's what it asks](setup.html).

To stop flexTri, press **Quit** in the top right of the app, or use the flexTri icon in the taskbar (Windows, Linux) or menu bar (Mac). Closing the browser tab alone leaves it running in the background, which is fine.
