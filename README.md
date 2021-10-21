# Night Guard Instruction


Night guard package aims to protect trades opened during rollover period. The current version is able to close positions with specified symbol and magic numbers after a certain time of a day.

### Installation
---

1. [Download](https://www.python.org/ftp/python/3.8.10/python-3.8.10-amd64.exe) and install Python 3.8.10 and tick the option **Add Python 3.8 to PATH** while installing.

2. Open PowerShell and run the following command to install necessary python packages

        py -m ensurepip --upgrade; py -m pip install pandas; py -m pip install MetaTrader5 



### Configuration
---

There are two files it needs to be configured.  Explanation of fields in `Config.txt`

* **mt5_exe_path**: Path to your mt5 terminal exe file
* **server**: The account trading server
* **login**: The account login
* **password**: The password
* **TEST**: 1 or 0, if its 1 then its in test mode, trades will NOT be closed, but rather records the profit as if it closes at stop time.

* **NS_START_HOUR**: Night trading start hour, usually put 22
* **NS_START_MINUTE**: Night trading start minute, usually put 58
* **NS_END_HOUR**: Night ends hour, usually put 0
* **NS_END_MINUTE**: Night ends hour, usually put 58

Specifies which trades should be managed, is in `symbol_stopT.csv`

* **Symbol**: Symbol with the name same as in your MT5.
* **StopT**: Time to close open positions, it has form of HH:MM:SS
* **Magic_start**: Magic number of the position
s


For magic number specification, there are two ways to use it. 

1. Magic numbers in a range. Put start magic number to `Magic_start`, end magic (includes) to `Magic_end`. Leave `Magics` fields empty.

2. A list of Magic numbers. Put the magic numbers in filed `Magics` connected by semi column "`;`", Leave the other two fields empty.

### How to use
---

1. Open MT5 terminal and login to your trading account, enable Algo Trading and make sure EURUSD listed on market watch.

2. Open PowerShell, and change working directory to NightGuard folder by 
    
        cd path_to_NightGuard_directory

3. Run the command:

        py .\nightguard\close_by_time.py

It should print out your account infomation means its working now. If want to exit, simply press Control+C


### Report
---

After all the specified trades closed each day, the position report will append to `OpenPositionReport.csv`. If `TEST` is set to `1`, the columns with ending `_if` will descript what if in live trading case.
