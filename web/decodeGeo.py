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
import urllib2


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



########################################################## MAIN ##########################################################
        
def main(argv):
    ip="128.186.19.133"
    baseUrlip= "http://api.ipapi.com/"
    print baseUrlip + ip + "?access_key=cc138a088a1a86604716a19dc20ad07a"
    ret=urllib2.urlopen(baseUrlip + ip + "?access_key=cc138a088a1a86604716a19dc20ad07a"); 
    print ret.read()
    #queryswifjobs="SELECT RunningLocation,RunIP FROM Attempts;"# && Status!='succeeded') )"
    #dbcursor.execute(queryswifjobs)
    #allAttempts = dbcursor.fetchall()
#
    #pairs=[{}]
    #for att in allAttempts:
    #    if(att["RunIP"] is not None ):
    #        pair={"loc": att["RunningLocation"], "IP": att["RunIP"]}
    #        #print str(att["RunningLocation"])+" | "+str(att["RunIP"])
    #        if pair in  pairs:
    #            continue
    #        else:
    #            pairs.append(pair)
#
    #print len(pairs)
#
    #for pair in pairs:
    #    query="UPDATE Attempts SET RunIP='"+str(pair.get("IP"))+"' where RunningLocation='"+str(pair.get("loc"))+"'"
    #    print query
    #    dbcursor.execute(query)
    #    dbcnx.commit()
    


    dbcnx.close()
              
if __name__ == "__main__":
   main(sys.argv[1:])
