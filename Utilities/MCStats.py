#!/usr/bin/env python
import MySQLdb
import sys
import datetime
import os.path
from optparse import OptionParser
import subprocess
from subprocess import call
from subprocess import Popen, PIPE
import socket
import pprint
import math
import matplotlib.pyplot as plt



dbhost = "hallddb.jlab.org"
dbuser = 'mcuser'
dbpass = ''
dbname = 'gluex_mc'

conn=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
curs=conn.cursor(MySQLdb.cursors.DictCursor)

class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def getTotalSizeOut():
    query= "SELECT TotalSizeOut From Project;"
    curs.execute(query) 
    rows=curs.fetchall()
    sum=0.0
    for proj in rows:
        if proj['TotalSizeOut'] == None:
            continue
        prefix=str(proj['TotalSizeOut'])[-2:-1]
        num=float(str(proj['TotalSizeOut'])[:-2])
        #print num
        #print "prefix is "+prefix
        total=0.0
        if(str(prefix)=="K"):
            #print "got K"
            total=num*1000.
        elif(str(prefix)=="M"):
            #print "got M"
            total=num*1000000.
        elif(prefix=='G'):
            #print "got G"
            total=num*1000000000.
        elif(prefix=='T'):
            #print "got G"
            total=num*1000000000000.
        elif(prefix=='E'):
            #print "got G"
            total=num*1000000000000000.
        #print str(proj['TotalSizeOut'])
        #print total
        sum+=total
        #print "==========================="
    
    print(sum/1000000000000)
    print("T")

def getUserProjectPercent():
    query= "SELECT UName From Project;"
    curs.execute(query) 
    rows=curs.fetchall()
    userlist=[]
    #print rows
    sum=0
    for proj in rows:
        #print proj['Email']
        sum+=1
        found=False
        for user in userlist:
            #print user.split("_")[0]+" vs "+proj['Email']
            if user.split("_")[0]==proj['UName']:
                #print "FOUND"
                index=userlist.index(user)
                found=True
                userlist[index]=user.split("_")[0]+"_"+str(int(user.split("_")[1])+1)
                break

        if not found:
            userlist.append(proj['UName']+"_1")

    print(userlist)

    sizes=[]
    labels=[]
    for user in userlist:
        userparse=user.split("_")
        print(userparse[0]+" | "+str(float(userparse[1])))#/float(sum))
        sizes.append(userparse[1])
        labels.append(userparse[0])

    fig1, ax1 = plt.subplots()
    l = ax1.pie(sizes, labels=labels, autopct='%1.1f%%',shadow=True, startangle=90, radius=10000,labeldistance=1.1) #labels=labels, plt.legend(patches, labels, loc='left center', bbox_to_anchor=(-0.1, 1.),fontsize=8)
    ax1.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

    for label, t in zip(labels, l[1]):
        x, y = t.get_position()
        angle = int(math.degrees(math.atan2(y, x)))
        ha = "left"
        va = "bottom"

        if angle > 90:
            angle -= 180

        if angle < 0:
            va = "top"

        if -45 <= angle <= 0:
            ha = "right"
            va = "bottom"

        #plt.annotate(label, xy=(x,y), rotation=angle, ha=ha, va=va, size=8)

    plt.show()

def getAttemptsTimes():
    query= "SELECT UNIX_TIMESTAMP(Start_Time),UNIX_TIMESTAMP(Completed_Time) From Attempts;"
    curs.execute(query) 
    rows=curs.fetchall()
    wallTimes=[]
    for att in rows:
        if(att['UNIX_TIMESTAMP(Completed_Time)'] == None or att['UNIX_TIMESTAMP(Start_Time)']==None):
            continue
        #print att['UNIX_TIMESTAMP(Completed_Time)']-att['UNIX_TIMESTAMP(Start_Time)']
        wallTimes.append(att['UNIX_TIMESTAMP(Completed_Time)']-att['UNIX_TIMESTAMP(Start_Time)'])

    fig, ax = plt.subplots(1,1)
    
    ax.hist(wallTimes, bins=50, color='lightblue')
    plt.show()

def main(argv):
    getTotalSizeOut()
    getUserProjectPercent()
    getAttemptsTimes()
        
        
    conn.close()
        

if __name__ == "__main__":
   main(sys.argv[1:])
