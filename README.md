# PC Dashboard

A small desktop widget for Windows that sits in a corner of your screen and shows:

- **System stats** (updated every second): CPU, memory, disk space, network speed, uptime, and battery on laptops.
- **A to-do list**: add tasks, tick them off, delete them. Tasks are saved automatically.

## Setup

1. Install [Python 3](https://www.python.org/downloads/) if you don't have it.
2. Install the one dependency:

   ```
   pip install -r requirements.txt
   ```

3. Double-click `pc_dashboard.pyw` to start it. The `.pyw` extension means it runs without a console window.

## Using it

- **Move it:** drag the title bar. It remembers where you put it.
- **Add a task:** type in the box and press Enter.
- **Complete a task:** click its checkbox or text. Click **Clear done** to remove finished tasks.
- **Delete a task:** click the ✕ next to it.
- **Options:** right-click anywhere on the widget:
  - Always on top
  - Start with Windows
  - Move to corner (top/bottom, left/right)
  - Opacity
  - Quit
- **Close it:** the ✕ in the top-right corner.

Your tasks and settings are stored in `%APPDATA%\PCDashboard\`, so updating the code won't erase them.
