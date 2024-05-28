#!/usr/bin/env python3
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
from subprocess import Popen, PIPE
import socket
import glob
import json
import time
from datetime import timedelta
from datetime import datetime
import smtplib
from email.message import EmailMessage
from multiprocessing import Process
import random
import pipes
import random
import pwd

MCWRAPPER_BOT_HOST_NAME=str(socket.gethostname())
dbhost = "hallddb.jlab.org"
dbuser = 'mcuser'
dbpass = ''
dbname = 'gluex_mc'

try:
        dbcnx=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
        dbcursor=dbcnx.cursor(MySQLdb.cursors.DictCursor)
except:
        print("WARNING: CANNOT CONNECT TO DATABASE.  JOBS WILL NOT BE CONTROLLED OR MONITORED")
        pass

runner_name=pwd.getpwuid( os.getuid() )[0]

if( not (runner_name=="tbritton" or runner_name=="mcwrap")):
    print("ERROR: You must be tbritton or mcwrap to run this script")
    sys.exit(1)

def exists_remote(host, path):
    """Test if a file exists at path on a host accessible with SSH."""
    status = subprocess.call(
        ['ssh', host, 'test -f {}'.format(pipes.quote(path))])
    if status == 0:
        return True
    if status == 1:
        return False
    raise Exception('SSH failed')

def CheckForFile(rootLoc,expFile):
    found=False
    subloc="hddm"
    parse_expFile=expFile.split(".")
    #print(parse_expFile[len(parse_expFile)-1])
    if(parse_expFile[len(parse_expFile)-1]=="root"):
        subloc="root/monitoring_hists"

    os.environ["BEARER_TOKEN_FILE"]="/var/run/user/10967/bt_u10967"
    os.environ["XDG_RUNTIME_DIR"]="/run/user/10967"
                
    token_str='eval `ssh-agent`; /usr/bin/ssh-add;'
    agent_kill_str="; ssh-agent -k"
    XROOTD_OUTPUT_ROOT="/gluex/mcwrap/REQUESTEDMC_OUTPUT/"
    XROOTD_SERVER="dtn-gluex.jlab.org"
    xrd_file_check="/usr/bin/xrdfs "+XROOTD_SERVER+" ls "+XROOTD_OUTPUT_ROOT+rootLoc+"/"+subloc+"/"+expFile

    print(token_str+xrd_file_check+agent_kill_str)
    my_env=os.environ.copy()

    p = Popen(token_str+xrd_file_check+agent_kill_str, env=my_env ,stdin=PIPE,stdout=PIPE, stderr=PIPE,bufsize=-1,shell=True,close_fds=True)
    output, errors = p.communicate()

    print("check for file:",xrd_file_check)
    #print("output:",output)
    #print("errors:",errors)

    xrd_found=False

    if "Unable to locate" not in str(errors, 'utf-8') and XROOTD_OUTPUT_ROOT+rootLoc+"/"+subloc+"/"+expFile in str(output, 'utf-8'):
        print("FILE FOUND VIA XROOTD")
        xrd_found=True

    #if(os.path.isfile('/osgpool/halld/tbritton/REQUESTEDMC_OUTPUT/'+rootLoc+"/"+subloc+"/"+expFile) or os.path.isfile('/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/'+rootLoc+"/"+subloc+"/"+expFile) or os.path.isfile('/mss/halld/gluex_simulations/REQUESTED_MC/'+rootLoc+"/"+subloc+"/"+expFile) ):
    if(os.path.isfile('/osgpool/halld/'+runner_name+'/REQUESTEDMC_OUTPUT/'+rootLoc+"/"+subloc+"/"+expFile) or exists_remote(runner_name+'@dtn1902','/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/'+rootLoc+"/"+subloc+"/"+expFile) or exists_remote(runner_name+'@dtn1902','/mss/halld/gluex_simulations/REQUESTED_MC/'+rootLoc+"/"+subloc+"/"+expFile) or exists_remote(runner_name+'@dtn1902','/work/halld/gluex_simulations/REQUESTED_MC/'+rootLoc+"/"+subloc+"/"+expFile) or xrd_found):
        found=True
    else:
        print(rootLoc+"/"+subloc+"/"+expFile+"   NOT FOUND")

    print("File found?",found)
    return found


def checkJobFilesForCompletion(comp_assignment):
    #OutstandingProjectsQuery="SELECT * FROM Project WHERE (Is_Dispatched != '0' && Tested != '-1' && Tested != '2' ) && Notified is NULL"
    #dbcursor.execute(OutstandingProjectsQuery)
    #OutstandingProjects=dbcursor.fetchall()
    dbcnx_comp=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
    dbcursor_comp=dbcnx_comp.cursor(MySQLdb.cursors.DictCursor)
    outdir_root="/osgpool/halld/"+runner_name+"/REQUESTEDMC_OUTPUT/"
    print("checking "+str(len(comp_assignment)))
    for attempt in comp_assignment:#OutstandingProjects:
        
        jobinfoq="SELECT * from Jobs where ID="+str(attempt["Job_ID"])
        dbcursor.execute(jobinfoq)
        job = dbcursor.fetchall()[0]

        projq="SELECT * From Project Where ID="+str(job["Project_ID"])
        dbcursor.execute(projq)
        proj = dbcursor.fetchall()[0]

        locparts=proj['OutputLocation'].split("/")

        #print("~~~~~~~~~~~~~~~~~~")
        #print("ProjID:",proj['ID'])
        files=[]
        dirs=[]
        #print locparts[len(locparts)-2]
        for r, dirs, files in os.walk(outdir_root+locparts[len(locparts)-2]) : 
            files = [f for f in files if not f[0] == '.']
            dirs[:] = [d for d in dirs if not d[0] == '.']

        #print("NumFiles:",len(files))
        #print(dirs)

       
        #DISTINCT ID ------in query below
       
        #print(fulfilledJobs)

        #print("Jobs fulfilled:",str(len(fulfilledJobs)))
        if(proj["Tested"]==2 or proj["Tested"]==3):
            continue

        rootLoc=proj['OutputLocation'].split("REQUESTED_MC")[1]#.replace("/","")
        nullify_list=[]
        
        
        #print("Data already Verified?",job['DataVerified'])
        if(job['DataVerified'] !=0 ):
            continue

        STANDARD_NAME=str(job['RunNumber']).zfill(6)+'_'+str(job['FileNumber']).zfill(3)
        if(proj['Generator']!="file:"):
            STANDARD_NAME=proj['Generator']+'_'+STANDARD_NAME
            #print(STANDARD_NAME)

        #check if postprocessor is being run
        postproc_append=""
        if(proj['GenPostProcessing'] != None and proj['GenPostProcessing'] != ""):
            print("Postprocessing:",proj['GenPostProcessing'])
            postproc_append="_"+proj['GenPostProcessing'].split(":")[0]

        Expected_returned_files=[]
            
        if(str(proj['RunGeneration'])=="1" and str(proj['SaveGeneration'])=="1" and str(proj['Generator'])!="particle_gun"):
            Expected_returned_files.append(STANDARD_NAME+postproc_append+".hddm")

        if(str(proj['RunGeant'])=="1" and str(proj['SaveGeant'])=="1"):
            Expected_returned_files.append(STANDARD_NAME+'_geant'+str(proj['GeantVersion'])+postproc_append+'.hddm')

        if(str(proj['RunSmear'])=="1" and str(proj['SaveSmear'])=="1"):
            Expected_returned_files.append(STANDARD_NAME+'_geant'+str(proj['GeantVersion'])+'_smeared'+postproc_append+'.hddm')
            
        if(str(proj['RunReconstruction'])=="1" and str(proj['SaveReconstruction'])=="1"):
            Expected_returned_files.append('dana_rest_'+STANDARD_NAME+postproc_append+'.hddm')
            Expected_returned_files.append('hd_root_'+STANDARD_NAME+postproc_append+'.root')
            
        found_AllexpFile=True

            
        for expFile in Expected_returned_files:
            #print(expFile)
            #print("checking for",expFile,"@",rootLoc)
            found=CheckForFile(rootLoc,expFile)
            if not found:
                #print(expFile+"   NOT FOUND!!!!")
                found_AllexpFile=False
                break
            
            
        if found_AllexpFile:

            Update_q="UPDATE Attempts Set Status=44,ExitCode=0 where ID="+str(attempt["ID"])
            print(Update_q)
            dbcursor_comp.execute(Update_q)
            dbcnx_comp.commit()
               
        else:
            continue
            


########################################################## MAIN ##########################################################
def array_split(lst,n):
    to_return=[]
    for i in range(0,n):
        to_return.append([])
    
    for count, ele in enumerate(lst):
        #print(ele)
        index=count%n
        #print(index)
        to_return[index].append(ele)

    #print(count)
    #print(len(to_return))

    return to_return

def main(argv):

        runnum=0
        runmax=-1
        spawnNum=10
        numOverRide=False

        if(len(argv) !=0):
            numOverRide=True
        
        numprocesses_running=subprocess.check_output(["echo `ps all -u "+runner_name+" | grep MCObserver.py | grep -v grep | wc -l`"], shell=True)

        print(int(numprocesses_running))
        if(int(numprocesses_running) <2 or numOverRide):
            while(runnum<runmax or runmax==-1):
                runnum=runnum+1
                
                try:
                    queryosgjobs="SELECT * from Attempts WHERE BatchSystem='OSG' && SubmitHost=\""+MCWRAPPER_BOT_HOST_NAME+"\" && Status !='4' && Status !='3' && Status!= '6' && Status != '5' && Status != '44';"# || (Status='4' && ExitCode != 0 && ProgramFailed is NULL) ORDER BY ID desc;"
                    #print queryosgjobs
                    dbcursor.execute(queryosgjobs)
                    Alljobs = list(dbcursor.fetchall())
                    #print(Alljobs[:5])
                    random.shuffle(Alljobs)
                    #print(Alljobs[:5])
                    Monitoring_assignments=array_split(Alljobs,spawnNum)
                    spawns=[]
                    for i in range(0,spawnNum):
                        time.sleep(random.randint(1,spawnNum))
                        print("block "+str(i))
                        print(len(Monitoring_assignments[i]))
                        if(len(Monitoring_assignments[i])>0):
                            p=Process(target=checkJobFilesForCompletion,args=(Monitoring_assignments[i],))
                            p.daemon = True
                            spawns.append(p)
                        
                        
                        #p.join()
                        
                    for i in range(0,len(spawns)):
                        #print("join "+str(i))
                        time.sleep(random.randint(1,spawnNum))
                        spawns[i].start()
                        
                    #time.sleep(2)
                    for i in range(0,len(spawns)):
                        if spawns[i].is_alive():
                            #print("join "+str(i))
                            spawns[i].join()


                except Exception as e:
                    print(e)
                    break


        dbcnx.close()
              
if __name__ == "__main__":
   main(sys.argv[1:])
