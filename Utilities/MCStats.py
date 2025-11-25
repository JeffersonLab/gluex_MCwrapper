#!/usr/bin/env python3
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
import numpy as np
import pandas as pd
import re

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


def getUserProjectPercent(graph=True):
    query= "SELECT UName, NumEvents From Project WHERE Submit_Time>DATE('2024-01-01') AND Notified=1 ORDER BY Submit_Time;"
    curs.execute(query) 
    rows=curs.fetchall()

    # store all info in a dictionary with usernames as keys
    userdict={}
    totalevents=0
    for proj in rows:
        totalevents = totalevents+proj['NumEvents']
        if proj['UName'] not in userdict:
            userdict[proj['UName']] = [0,0]
        numUserProj = userdict[proj['UName']][0] + 1
        numUserEvents = userdict[proj['UName']][1] + proj['NumEvents']
        userdict[proj['UName']] = (numUserProj, numUserEvents)

    print(userdict)

    # convert to df for some easy manipulations
    userdf = pd.DataFrame.from_dict(userdict,orient='index',columns=['NumProj','NumEvents'])
    print(userdf)
    proj_sum=0
    sizes=[]
    labels=[]
    for user in userdict:
        sizes.append(userdict[user][1])
        labels.append(user)
        proj_sum+=float(userdict[user][0])

    print(len(userdict),proj_sum,totalevents)

    if graph:
        userdf.plot.pie(subplots=True, figsize=(10,5))

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

            # plt.annotate(label, xy=(x,y), rotation=angle, ha=ha, va=va, size=8)

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


def getStartAndLength():
    query= "SELECT UNIX_TIMESTAMP(Start_Time),CPUTime From Attempts where CPUTime != 0;"
    curs.execute(query) 
    rows=curs.fetchall()
    totaltime=datetime.timedelta(0)
    Starttimes=[]
    for time in rows:
        Starttimes.append(time["UNIX_TIMESTAMP(Start_Time)"])
        totaltime=totaltime+time["CPUTime"]
        # print(str(time["UNIX_TIMESTAMP(Start_Time)"])+" , "+str(time["CPUTime"]))

    print(totaltime)
    fig, ax = plt.subplots(1,1)

    ax.hist(Starttimes, bins=6, color='lightblue')
    plt.show()


def getUsageTimeline():
    query= "SELECT UName, Submit_Time, NumEvents FROM Project WHERE Submit_Time>DATE('2024-01-01') AND Notified=1 ORDER BY Submit_Time;"
    curs.execute(query) 
    rows=curs.fetchall()

    # Store the result in a dictionary with name as the key
    result = {}
    alldata = []
    for data in rows:
        if data['UName'] not in result:
            result[data['UName']] = []
        result[data['UName']].append((data['Submit_Time'], data['NumEvents']))
        alldata.append((data['Submit_Time'], data['NumEvents']))

    # re-sum all events into weeks
    resummed_data = []
    prevweek = -1
    runningsum = 0
    for date, events in alldata:
        runningsum = runningsum + events

        year, week, day = date.isocalendar()
        if week != prevweek:
            resummed_data.append((date,runningsum))
            runningsum = 0
            prevweek = week

    x = [Submit_Time for Submit_Time, NumEvents in resummed_data]
    y = [NumEvents for Submit_Time, NumEvents in resummed_data]
    plt.plot(x, y)

    # Plot the data for each name
    # for UName, data in result.items():
    #     x = [Submit_Time for Submit_Time, NumEvents in data]
    #     y = [NumEvents for Submit_Time, NumEvents in data]
    #     plt.plot(x, y, label=UName)

    # Add labels and legend to the plot
    plt.xlabel("Time")
    plt.ylabel("NumEvents")
    plt.title("Number of events requested per week")
    plt.legend()

    plt.show()


def getRunningLocations():
    isostartdate = '2024-01-01'
    startdate = datetime.date.fromisoformat(isostartdate)

    query= "SELECT RunningLocation,Start_Time,WallTime,CPUTime,RAMUsed,ExitCode FROM Attempts WHERE Start_Time>DATE('"+isostartdate+"') ORDER BY Start_Time;"
    curs.execute(query) 
    rows=curs.fetchall()

    # Store the result in a list
    alldata = []
    for data in rows:
        alldata.append((data['RunningLocation'], data['Start_Time'], data['WallTime'], data['CPUTime'], data['RAMUsed'], data['ExitCode']))
    # print(alldata)

    #sort into running locations by looking at those relevant for GlueX
    runningLocs = {}
    runningLocs['JLab'] = []
    runningLocs['UConn'] = []
    runningLocs['FSU'] = []
    runningLocs['Glasgow'] = []
    runningLocs['IU'] = []
    runningLocs['ComputeCanada'] = []
    runningLocs['Other'] = []
    for data in alldata:
        if 'jlab.org' in data[0]:
            runningLocs['JLab'].append(data)
        elif 'uconn.edu' in data[0]:
            runningLocs['UConn'].append(data)
        elif 'fsu.edu' in data[0]:
            runningLocs['FSU'].append(data)
        elif 'beowulf.cluster' in data[0] or re.search(r'@wn-d|h\d{2}-\d{3}', data[0]):
            runningLocs['Glasgow'].append(data)
        elif 'iu.edu' in data[0] or 'IU-Jetstream2' in data[0]:
            runningLocs['IU'].append(data)
        elif 'computecanada.ca' in data[0]:
            runningLocs['ComputeCanada'].append(data)
        else:
            runningLocs['Other'].append(data)

    # print length of each location
    for loc in runningLocs:
        print(loc, len(runningLocs[loc]))

    # plot running locations as pie chart with number of jobs as size (remove empty locations)
    sizes = [len(runningLocs[loc]) for loc in runningLocs if len(runningLocs[loc]) > 0]
    labels = [loc for loc in runningLocs if len(runningLocs[loc]) > 0]

    fig1, ax1 = plt.subplots()
    ax1.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90)
    ax1.axis('equal')  # Equal aspect ratio ensures that pie is drawn as a circle.

    plt.title("Number of jobs per running location")
    plt.show()

    # plot running locations as pie chart with WallTime as size
    # plot running locations as pie chart with CPUTime as size

    # plot number of jobs per week using Start_Time for each location
    for loc in runningLocs:
        if len(runningLocs[loc]) == 0:
            continue

        # re-sum all events into weeks, while making sure empty weeks get a 0 and year changes are properly accounted for
        resummed_data = []
        prevweek = (startdate-datetime.timedelta(weeks=1)).isocalendar()[1] #find previous week (make sure year is correct)
        runningsum = 0
        for data in runningLocs[loc]:
            date = data[1]
            year, week, day = date.isocalendar()

            # treat special case of year change
            if week-prevweek < 0:
                while week-prevweek < 0:
                    resummed_data.append((datetime.date.fromisocalendar(year-1, prevweek, 1),runningsum))
                    runningsum = 0
                    if prevweek == 52:
                        prevweek = 0
                    prevweek = prevweek + 1
                runningsum = 0

            # treat special case of empty weeks
            if week-prevweek > 1:
                while week-prevweek > 0:
                    resummed_data.append((datetime.date.fromisocalendar(year, prevweek, 1),runningsum))
                    runningsum = 0
                    prevweek = prevweek + 1
                runningsum = 0
                prevweek = week # should be redundant here

            # treat normal case of progressing weeks
            if week-prevweek == 1:
                resummed_data.append((datetime.date.fromisocalendar(year, prevweek, 1),runningsum))
                runningsum = 0
                prevweek = week

            runningsum = runningsum + 1
            
        resummed_data.append((datetime.date.fromisocalendar(year, prevweek, 1),runningsum)) # add the last week

        x = [Submit_Time for Submit_Time, NumJobs in resummed_data]
        y = [NumJobs for Submit_Time, NumJobs in resummed_data]
        plt.plot(x, y, label=loc)
        print(loc, x, y)

    # Add labels and legend to the plot
    plt.xlabel("Time")
    plt.ylabel("NumJobs")
    plt.title("Percentage of jobs run per week per OSG location")
    plt.legend()
    plt.show()


def main(argv):
    # getTotalSizeOut()
    getUserProjectPercent(True)
    # getAttemptsTimes()
    # getStartAndLength()
    # getUsageTimeline()
    getRunningLocations()

    conn.close()


if __name__ == "__main__":
   main(sys.argv[1:])


# SELECT COUNT(*),SUM(NumEvents) FROM Project WHERE Dispatched_Time>DATE('2024-01-01') AND Notified=1 ORDER BY Dispatched_Time;
# SELECT COUNT(*) FROM Jobs WHERE Project_ID IN (SELECT ID FROM Project WHERE Dispatched_Time>DATE('2024-01-01') AND Notified=1);
