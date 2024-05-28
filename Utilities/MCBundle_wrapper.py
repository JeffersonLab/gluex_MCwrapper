#!/usr/bin/env python3
import MySQLdb
#import MySQLdb.cursors
from os import environ
from optparse import OptionParser
import os.path
#import mysql.connector
import time
import os
import pwd
import getpass
import sys
import re
import subprocess
from subprocess import call, Popen, PIPE
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
import shutil
import shlex

dbhost = "hallddb.jlab.org"
dbuser = 'mcuser'
dbpass = ''
dbname = 'gluex_mc'

try:
        dbcnx=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
        dbcursor=dbcnx.cursor(MySQLdb.cursors.DictCursor)
except:
        print("WARNING: CANNOT CONNECT TO DATABASE. DON'T KNOW WHAT TO DO.")
        exit(1)

# def array_split(lst,n):
#     to_return=[]
#     for i in range(0,n):
#         to_return.append([])
    
#     for count, ele in enumerate(lst):
#         #print(ele)
#         index=count%n
#         #print(index)
#         to_return[index].append(ele)

#     #print(count)
#     #print(len(to_return))

#     return to_return

# def BundleAll(tobundle):
#     for proj in tobundle:
#         print(proj)
#         inputdir= proj["OutputLocation"].replace("/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/","/work/test-xrootd/gluex/mcwrap/REQUESTEDMC_OUTPUT/")
#         outputlocation="/".join(proj["OutputLocation"].split("/")[:-1])+"/"
        
#         #update project status
#         runbundle=21
#         if proj["Tested"]==40:
#             runbundle=41
#         update_q="UPDATE Project SET Tested="+str(runbundle)+" WHERE ID="+str(proj["ID"])
#         dbcnx=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
#         dbcursor=dbcnx.cursor(MySQLdb.cursors.DictCursor)
#         dbcursor.execute(update_q)
#         dbcnx.commit()
#         dbcnx.close()
#         out=BundleFiles(inputdir,outputlocation)
#         dbcnx=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
#         dbcursor=dbcnx.cursor(MySQLdb.cursors.DictCursor)
#         if(out=="SUCCESS"):
#             #update project status
#             update_q="UPDATE Project SET Tested=100 WHERE ID="+str(proj["ID"])
#             dbcursor.execute(update_q)
#             dbcnx.commit()
#         else:
#             #update project status
#             rebundle=20
#             if proj["Tested"]==41:
#                 rebundle=40
#             update_q="UPDATE Project SET Tested="+str(rebundle)+" WHERE ID="+str(proj["ID"])
#             dbcursor.execute(update_q)
#             dbcnx.commit()
#         dbcnx.close()

def BundleFiles(inputdir,output):
    MCWRAPPER_BOT_HOME="/scigroup/mcwrapper/gluex_MCwrapper/"
    projectName = inputdir.split("/")[-2] if inputdir[-1]=="/" else inputdir.split("/")[-1]
    mkdircommand="mkdir -p /osgpool/halld/mcwrap/mergetemp/" + projectName
    print(mkdircommand)
    subprocess.call(mkdircommand.split(" "))
    mkdircommand="mkdir -p "+output
    print(mkdircommand)
    subprocess.call(mkdircommand.split(" "))
    # bundlecommand = "echo hostname; source /group/halld/Software/build_scripts/gluex_env_jlab.sh; /usr/bin/python3.6 " + MCWRAPPER_BOT_HOME + "/Utilities/MCMerger.py -f -tempdir /osgpool/halld/mcwrap/mergetemp/" + projectName + "/ " + inputdir + " " + output
    bundlecommand = "/usr/bin/python3.6 " + MCWRAPPER_BOT_HOME + "/Utilities/MCMerger.py -tempdir /osgpool/halld/mcwrap/mergetemp/" + projectName + "/ " + inputdir + " " + output + " -noclean"# + " > "+projectName+"_"+str(datetime.now())+".log"
    print("BUNDLING WITH",bundlecommand)
    try:
        suboutput = subprocess.check_output(shlex.split(bundlecommand), stderr=subprocess.STDOUT)
        #find the number after "Returning final_success:"
        out = int(re.findall(r"Returning final_success: (\d+)", suboutput.decode('utf-8'))[0])

        print("subprocess output", out)
        if out==-666:
            print("Bundling ongoing")
            return "ONGOING"
        print("Bundler return code", out)
        subprocess.run([f"rm /osgpool/halld/mcwrap/mergetemp/{projectName}/.merging"], shell=True)
        if out==0:
            return "SUCCESS"
        else:
            return "ERROR"
    except subprocess.CalledProcessError as e:
        print(e.output)
        subprocess.run([f"rm /osgpool/halld/mcwrap/mergetemp/{projectName}/.merging"], shell=True)
        return "ERROR"

def main(argv):
    runner_name=pwd.getpwuid( os.getuid() )[0]
    numprocesses_running=subprocess.check_output(["echo `ps all -u "+runner_name+" | grep MCBundle_wrapper.py | grep -v grep | wc -l`"], shell=True)
    spawnNum=2
    print(f"numprocesses_running: {int(numprocesses_running)}")

    if(int(numprocesses_running)>spawnNum):
        print(f"{int(numprocesses_running)} process(es) of MCBundle_wrapper.py already running.  Exiting.")
        exit(0)
    else:
        print(f"{int(numprocesses_running)} process(es) of MCBundle_wrapper.py running.  Continuing.")
        #get projects with Tested>=20
        # tobundle_q="SELECT * FROM Project WHERE Tested=20 OR Tested=40 LIMIT 1"
        # tobundle_q="SELECT * FROM Project WHERE (Tested=20 OR Tested=40) AND Notified is NULL AND ID != 3476 order by ID asc LIMIT 1"
        tobundle_q="SELECT * FROM Project WHERE (Tested=20 OR Tested=40) AND Notified is NULL AND ID != 3476 order by NumEvents asc LIMIT 1"
        print(tobundle_q)
        dbcnx=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
        dbcursor=dbcnx.cursor(MySQLdb.cursors.DictCursor)
        dbcursor.execute(tobundle_q)
        tobundle=dbcursor.fetchall()
        print(tobundle)

        
        for proj in tobundle:
            print(proj)
            inputdir= proj["OutputLocation"].replace("/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/","/work/test-xrootd/gluex/mcwrap/REQUESTEDMC_OUTPUT/")
            
            #dirty hack to treat special case of ppauli subdir, NEED TO RESOLVE ASAP
            inputdir = inputdir.replace("ppauli/","") if "ppauli/" in inputdir else inputdir

            outputlocation="/".join(proj["OutputLocation"].split("/")[:-1])+"/"
            
            #update project status
            print(proj["ID"])

            projectName = inputdir.split("/")[-2] if inputdir[-1]=="/" else inputdir.split("/")[-1]
            #check if already being bundled
            print("/osgpool/halld/mcwrap/mergetemp/"+projectName+"/.merging")
            
            if os.path.isfile("/osgpool/halld/mcwrap/mergetemp/"+projectName+"/.merging"):
                print("Currently being bundled")
                continue

            runbundle=50
            if proj['Tested']==40:
                runbundle=41
            elif proj['Tested']==20:
                runbundle=21

            if runbundle == 50:
                return
            
            update_q="UPDATE Project SET Tested="+str(runbundle)+" WHERE ID="+str(proj["ID"])
            print(update_q)
            dbcursor.execute(update_q)
            dbcnx.commit()

            #verify Tested has been updated
            verify_q="SELECT Tested FROM Project WHERE ID="+str(proj["ID"])
            dbcursor.execute(verify_q)
            ptest=dbcursor.fetchone()
            if ptest["Tested"]!=runbundle:
                print("ERROR: Tried to update project status to "+str(runbundle)+" but it is "+str(ptest["Tested"]))
                exit(1)

            dbcnx.close()

            print("BEGINNING BUNDLE")
            out=BundleFiles(inputdir,outputlocation)
            
            dbcnx=MySQLdb.connect(host=dbhost, user=dbuser, db=dbname)
            dbcursor=dbcnx.cursor(MySQLdb.cursors.DictCursor)

            print("OUT: ",out)
            if(out=="SUCCESS"):
                #update project status
                comp=500
                if runbundle==21:
                    comp=100
                elif runbundle==41:
                    comp=400
                update_q="UPDATE Project SET Tested="+str(comp)+" WHERE ID="+str(proj["ID"])
                dbcursor.execute(update_q)
                dbcnx.commit()
            elif(out=="ONGOING"):
                print("Bundling ongoing. Will try again later, if needed.")
            else:
                #update project status
                rebundle=int(proj["Tested"])

                if rebundle==41:
                    rebundle=40
                elif rebundle==21:
                    rebundle=20
                
                update_q="UPDATE Project SET Tested="+str(rebundle)+" WHERE ID="+str(proj["ID"])
                dbcursor.execute(update_q)
                dbcnx.commit()
            dbcnx.close()




        # spawns = []
        # #split tobundle into spawnNum lists
        # Bundling_assignments=array_split(tobundle,spawnNum)
        # for i in range(0,spawnNum):
        #     time.sleep(random.randint(1,spawnNum))
        #     print("block "+str(i))
        #     print(len(Bundling_assignments[i]))
        #     if(len(Bundling_assignments[i]) !=0 ):
        #         p=Process(target=BundleAll,args=(Bundling_assignments[i],))
        #         p.daemon = True
        #         spawns.append(p)


        # dbcnx.close()
        # #spawn spawnNum processes
        # for p in spawns:
        #     p.start()
        # #collect all processes
        # for p in spawns:
        #     if p.is_alive():
        #         p.join()

if __name__ == "__main__":
   main(sys.argv[1:])
