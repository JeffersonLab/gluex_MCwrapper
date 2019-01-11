#!/usr/bin/env python
##########################################################################################################################
#
# 2017/03 Thomas Britton
#
#   Options:
#      MC variation can be changed by supplying "variation=xxxxx" option otherwise default: mc
#      the number of events to be generated per file (except for any remainder) can be set by "per_file=xxxx" default: 1000
#
#      If the user does not want genr8, geant, smearing, reconstruction to be performed the sequence will be terminated at the first instance of genr8=0,geant=0,mcsmear=0,recon=0 default: all on
#      Similarly, if the user wishes to retain the files created by any step you can supply the cleangenr8=0, cleangeant=0, cleanmcsmear=0, or cleanrecon=0 options.  By default all but the reconstruction files #      are cleaned. 
#
#      The reconstruction step is multi-threaded, for this step, if enabled, the script will use 4 threads.  This threading can be changed with the "numthreads=xxx" option 
#
#      By default the job will run interactively in the local directory.  If the user wishes to submit the jobs to swif the option "swif=1" must be supplied.
#
# SWIF DOCUMENTATION:
# https://scicomp.jlab.org/docs/swif
# https://scicomp.jlab.org/docs/swif-cli
# https://scicomp.jlab.org/help/swif/add-job.txt #consider phase!
#
##########################################################################################################################
import MySQLdb
#import MySQLdb.cursors
from os import environ
from optparse import OptionParser
import os.path
#import mysql.connector
import time
import os
import getpass
import sys
import re
import subprocess
from subprocess import call
import socket
import glob
import json
import time
from datetime import timedelta
from datetime import datetime

dbhost = "hallddb.jlab.org"
dbuser = 'mcuser'
dbpass = ''
dbname = 'gluex_mc'

try:
        dbcnx=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
        dbcursor=dbcnx.cursor(MySQLdb.cursors.DictCursor)
except:
        print "WARNING: CANNOT CONNECT TO DATABASE.  JOBS WILL NOT BE CONTROLLED OR MONITORED"
        pass

def DroneDo(id):

        try:
                drone_directive=os.environ["MCWRAPPER_CENTRAL"]+"/Utilities/MCDispatcher.py autolaunch"
                retcode=subprocess.call(drone_directive.split(" "))
        except subprocess.CalledProcessError as exc:
            dbcursor.execute("UPDATE MCDrone SET Status='Fail' where ID="+str(id))
            dbcnx.commit()
            exit(1)
        else:
            pass



def main(argv):

        numOverRide=False

        if(len(argv) !=0):
		    numOverRide=True
        
        numprocesses_running=subprocess.check_output(["echo `ps all -u tbritton | grep MCDrone.py | grep -v grep | wc -l`"], shell=True)

        print int(numprocesses_running)
        ALLSTOP=False
        if(os.path.isfile('/osgpool/halld/tbritton/.ALLSTOP')):
            print("ALL STOP DETECTED")
            ALLSTOP=True

        if( (int(numprocesses_running) <2 or numOverRide) and not ALLSTOP):
            dbcursor.execute("INSERT INTO MCDrone (Host,StartTime,Status) VALUES ('"+str(socket.gethostname())+"', NOW(), 'Running' )")
            dbcnx.commit()
            queryoverlords="SELECT MAX(ID) FROM MCDrone;"
            dbcursor.execute(queryoverlords)
            lastid = dbcursor.fetchall()
            
            try:
                DroneDo(lastid[0]["MAX(ID)"])
                dbcursor.execute("UPDATE MCDrone SET EndTime=NOW(), Status='Success' where ID="+str(lastid[0]["MAX(ID)"]))
                dbcnx.commit()
            except:
                dbcursor.execute("UPDATE MCDrone SET Status='Fail' where ID="+str(lastid[0]["MAX(ID)"]))
                dbcnx.commit()
                pass


        dbcnx.close()
              
if __name__ == "__main__":
   main(sys.argv[1:])
