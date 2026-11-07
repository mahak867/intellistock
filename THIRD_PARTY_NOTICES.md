# Third-party notices

## day-trader-skill

`backend/tools/timemachine.py` and `backend/tools/pretrade.py` are adapted from
`trader-timemachine/timemachine.py`, `trader-risk/check.py` and `trader-budget/size.py` in
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill). The changes:
daily NSE/BSE bars and a holding period in days instead of 5-minute US bars, a block bootstrap,
gap fills at the open, round-trip costs in R, rupees, NSE hours in IST, F&O lot sizes, and a
drawdown table for the whole portfolio.

```
MIT License

Copyright (c) 2026 Jake Schincariol

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
