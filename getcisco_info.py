

from datetime import datetime
import csv
import netmiko
import sys
import re
import pandas as pd
import textfsm


def getLoginInfo(csvFile):
    """
    Function to create list of dictionaries from CSV file.
    """
    with open(csvFile, "r") as swfile:
        reader = csv.DictReader(swfile)
        data = []
        for line in reader:
            data.append(line)
    return data


def convertLoginDict(data):
    """
    Converts list of dictionaries to list of lists
    """
    try:
        swlist = [[row["ipaddr"], row["username"], row["password"]] for row in data]
        return swlist
    except KeyError:
        print("\nInvalid header in CSV file. Please modify to the format below: "
              "\nipaddr,username,password"
              "\n192.168.50.14,admin,cisco"
              "\n10.43.20.21,admin,cisco\n"
              )
        sys.exit()


def getDevInfo(ip, user, pwd):
    """
    Function logs in to Cisco Switch and executes
    'show version', 'show mac address-table int' and 'show ip arp | include' on each device.
    Parses out serial number,PID,IOS,hostname,macs on interfaces and looks for a match of mac address to ip address in arp table
    """
    session = {
        "device_type": "cisco_ios",
        "ip": ip,
        "username": user,
        "password": pwd,
        "verbose": False,
        "secret": pwd,
        "fast_cli": False
    }
    
    session_gw = {
        "device_type": "cisco_ios",
        "ip": "10.14.241.65",
        "username": user,
        "password": pwd,
        "verbose": False,
        "secret": pwd
    }
    
    try:
        print("Connecting to switch {switch}".format(switch=ip))
        conn = netmiko.ConnectHandler(**session)
        info = conn.send_command("show version")
        sn = re.findall(r'Processor\sboard\sID\s(\S+)', info)[0]
        pid = re.findall(r"[Cc]isco\s(\S+).*memory.", info)[0]
        ios = re.findall(r'System\simage\sfile\sis\s"([^ "]+)', info)[0]
        hostname = re.findall(r'(\S+)\suptime', info)[0]

        devdata = {'Product ID':pid,
                   'Serial Number':sn,
                   'IOS':ios,
                   'IP':ip,
                   'Hostname':hostname,
                   'Status':'Success'}

        conn_gw = netmiko.ConnectHandler(**session_gw)
        mac_table = conn.send_command("show int status", use_textfsm=True)
        for item in mac_table:
            mac_table_int = conn.send_command("show mac address-table int {}".format(item['port']))
            #print("show mac address-table int {}".format(item['port']))
            #print(mac_table_int)
            with open('mac.template') as template:
                fsm = textfsm.TextFSM(template)
                result = fsm.ParseText(mac_table_int)
            result = ' '.join([' '.join(strings) for strings in result]).replace(' ',',')
            #print('result = ' + result)
            item.update({'mac':result})
            item.update({'ip':''})
            if item.get('vlan') != 'trunk':
                result_arp = []
                for mac in item['mac'].split(','):
                    arp_tab = conn_gw.send_command("show ip arp | include {}".format(mac))
                    with open('arp.template') as template:
                        fsm = textfsm.TextFSM(template)
                        arp = fsm.ParseText(arp_tab)
                    arp = ' '.join([' '.join(strings) for strings in arp]).replace(' ',',')
                    result_arp.append(arp) 
                result_arp = ' '.join([' '.join(strings) for strings in result_arp]).replace(' ','')
                item.update({'ip':result_arp})

        tab = { 'interface': [entry['port'] for entry in mac_table],
                'description': [entry['name'] for entry in mac_table],
                'status': [entry['status'] for entry in mac_table],
                'vlan': [entry['vlan'] for entry in mac_table],
                'mac':  [entry['mac'] for entry in mac_table],
                'ip': [entry['ip'] for entry in mac_table]
                }
        print("Collection successful from switch {switch}".format(switch=ip))
        return devdata,tab,hostname
    except netmiko.NetMikoTimeoutException:
        devdata = {'Product ID':'',
                   'Serial Number':'',
                   'IOS':'',
                   'IP':ip,
                   'Hostname':'',
                   'Status':'Fail Device Unreachable/SSH not enabled'}
        tab = ''
        hostname = ''
        print(ip,' Fail Device Unreachable/SSH not enabled')
        return devdata,tab,hostname
    except netmiko.NetMikoAuthenticationException:
        devdata = {'Product ID':'',
                   'Serial Number':'',
                   'IOS':'',
                   'IP':ip,
                   'Hostname':'',
                   'Status':'Fail Authentication'}
        tab = ''
        hostname = ''
        print(ip,' Fail Authentication')
        return devdata,tab,hostname
#    except netmiko.SSHException:
#        devdata = {'Product ID':'',
#                   'Serial Number':'',
#                   'IOS':'',
#                   'IP':ip,
#                   'Hostname':'',
#                   'Status':'Fail SSH not enabled'}
#        tab = ''
#        hostname = ''
#        print(ip,' Fail')
#        return devdata,tab,hostname
    except AttributeError:
        devdata = {'Product ID':'',
                   'Serial Number':'',
                   'IOS':'',
                   'IP':ip,
                   'Hostname':'',
                   'Status':'Regex match error. Missing info for device'}
        tab = ''
        hostname = ''
        print(ip,' Regex match error. Missing info for device')
        return devdata,tab,hostname


def main(args):

    # Define start time
    start_time = datetime.now()

    # Import CSV file and generate list of dictionaries
    csvFile = sys.argv[1]
    data = getLoginInfo(csvFile)

    # Convert list of dictionaries to list of lists
    swlist = convertLoginDict(data)

    devdata_summ = []
    dev_tab_summ = []
    hostname_summ = []
    for item in swlist:
        devdata,dev_tab,hostname = getDevInfo(*item)
        devdata_summ.append(devdata)
        if dev_tab != '':              
            dev_tab_summ.append(dev_tab)
            hostname_summ.append(hostname)
            
    devices = { 'Product ID': [entry['Product ID'] for entry in devdata_summ],
                'Serial Number': [entry['Serial Number'] for entry in devdata_summ],
                'IOS': [entry['IOS'] for entry in devdata_summ],
                'IP': [entry['IP'] for entry in devdata_summ],
                'Hostname':  [entry['Hostname'] for entry in devdata_summ],
                'Status': [entry['Status'] for entry in devdata_summ]
                }

    df_devices = pd.DataFrame(devices, columns=list(devices.keys()))
    writer = pd.ExcelWriter('mac_table.xlsx', engine='xlsxwriter')
    df_devices.index += 1 
    df_devices.to_excel(writer, 'Devices',index_label='№')
    i = 0
    for tab in dev_tab_summ:
        pd.DataFrame(tab, columns=list(tab.keys())).to_excel(writer, sheet_name=hostname_summ[i], index=False)
        i += 1

    writer.save()       

    print("\nReview collected information in mac_table.xlsx")
    print("\nElapsed time: " + str(datetime.now() - start_time))


if __name__ == "__main__":
    if len(sys.argv) == 2:
        main(sys.argv)
    else:
        print(
            "\nThis program is designed to retrieve the PID,serial number,ios,hostname and connected devices on interfaces (mac, ip).\n"
            "Creates xlsx file with sheets for each switch.\n"
            "\nThe program accepts argument. The name of a CSV file.\n "
            "\nThe CSV should be in the format below:\n"
            "\nipaddr,username,password"
            "\n10.13.23.10,admin,cisco"
            "\n192.160.10.31,admin,cisco\n"
            "\nUsage: python get_Ciscoinfo.py Device.csv\n"
        )
        sys.exit()
