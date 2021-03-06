# Night Guard Instruction


Night guard package aims to protect trades opened during rollover period. The current version is able to close positions with specified symbol and magic numbers after a certain time of the day.

### Installation
---

1. [Download](https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe) and install Python 3.8.10 and tick the option **Add Python 3.8 to PATH** while installing.

2. Open PowerShell and run the following command to install necessary python packages

        py -m ensurepip --upgrade; py -m pip install -r requirement.txt


### Configuration
---

There are two files that needs to be configured.  Explanation of fields in `Config.ini`

* **mt5_exe_path**: Path to your mt5 terminal exe file
* **server**: The account trading server
* **login**: The account login
* **password**: The password
* **TEST**: 1 or 0, if its 1 then its in test mode, trades will NOT be closed, but rather records the profit as if it closes at stop time.

* **NS_END_HOUR**: Night ends hour, usually put 0
* **NS_END_MINUTE**: Night ends hour, usually put 58

Specifies which trades should be managed, is in `symbol_stopT.csv`

* **Symbol**: Symbol with the name same as in your MT5.
* **StopT**: Time to close open positions, it has form of HH:MM:SS
* **Magics**: Magic number of the positions

   A list of Magic numbers. Put the magic numbers in filed `Magics` connected by semi column "`;`", empty values means all the trades opened after 23:00.

### How to use
---

1. Open MT5 terminal and login to your trading account, enable Algo Trading and make sure EURUSD is listed on market watch.

2. Open PowerShell, and change the working directory to NightGuard folder by 
    
        cd "path_to_NightGuard_directory"

3. Run the command:

        py main.py

It should print out your account information means it's working now. If want to exit, simply press Control+C


### Report
---

After all the specified trades are closed each day, the position report will append to `PositionReport.csv`. If `TEST` is set to `1`, the columns with leading `ST_` will descript what if activate stop time closing, in live trading case.
