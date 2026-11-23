#!/usr/bin/env python3
"""Copper resistance of the battery / firing path of the routed v2 board (tracks + vias network solve,
tools/pcb/netres.py; outer 35 um, inner 35 um or 17.5 um with 'half').
Run: /usr/bin/python3 tools/pcb/fire_path_res.py [half]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if 'half' in sys.argv[1:]:
    sys.argv.append('--inner-half')
import netres as N
b = N.b


def pad(ref, net):
    fp = b.FindFootprintByReference(ref)
    return (ref, [p.GetNumber() for p in fp.Pads() if p.GetNetname() == net][0])


N.analyse('/BAT_P', [(pad('BT1', '/BAT_P'), pad('Q28', '/BAT_P'))])
N.analyse('/BAT_PF', [(pad('Q28', '/BAT_PF'), pad('F1', '/BAT_PF'))])
N.analyse('/BAT_SW', [(pad('F1', '/BAT_SW'), pad('SW1', '/BAT_SW'))])
N.analyse('/VSYS', [(pad('SW1', '/VSYS'), pad('Q27', '/VSYS')), (pad('SW1', '/VSYS'), pad('D51', '/VSYS')),
                    (pad('SW1', '/VSYS'), pad('U11', '/VSYS'))])
N.analyse('/VFIRE', [(pad('Q27', '/VFIRE'), ('J%d' % i, 'S')) for i in (1, 12, 13, 24)])
N.analyse('/CH12', [(('J13', 'T'), pad('Q13', '/CH12'))])
