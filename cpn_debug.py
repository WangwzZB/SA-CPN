#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
from ryu.cmd import manager
def main():
    #用要调试的脚本的完整路径取代/home/tao/workspace/python/ryu_test/app/simple_switch_lacp_13.py就可以了
    sys.argv.append('/home/wwz/ryu/ryu/app/network_awareness/cpn_routing.py')
    # sys.argv.append('--verbose')
    sys.argv.append('--enable-debugger')
    sys.argv.append('--observe-links')
    sys.argv.append('--k-paths=1')
    sys.argv.append('--weight=hop')
    manager.main()

if __name__ == '__main__':
   main()