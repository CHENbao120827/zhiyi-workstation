# -*- coding: utf-8 -*-
s = open(r'C:\Users\ChenZ\Desktop\智己工作站\server.py', encoding='utf-8').read()
i = s.find("'/api/service'")
print('SERVICE AREA:', s[max(0, i-100):i+1600])
