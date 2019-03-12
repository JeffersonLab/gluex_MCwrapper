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


def WritePayloadConfig(order,foundConfig):
    
    MCconfig_file= open("MCDispatched.config","a")
    MCconfig_file.write("PROJECT="+str(order["Exp"])+"\n")

    if str(order["Exp"]) == "CPP":
        MCconfig_file.write("VARIATION=mc_cpp"+"\n")
        MCconfig_file.write("FLUX_TO_GEN=cobrems"+"\n")

    splitlist=order["OutputLocation"].split("/")
    MCconfig_file.write("WORKFLOW_NAME="+splitlist[len(splitlist)-2]+"\n")
    MCconfig_file.write(order["Config_Stub"]+"\n")
    MinE=str(order["GenMinE"])
    if len(MinE) > 5:
        cutnum=len(MinE)-5
        MinE = MinE[:-cutnum]
    MaxE=str(order["GenMaxE"])
    if len(MaxE) > 5:
        cutnum=len(MaxE)-5
        MaxE = MaxE[:-cutnum]
    MCconfig_file.write("GEN_MIN_ENERGY="+MinE+"\n")
    MCconfig_file.write("GEN_MAX_ENERGY="+MaxE+"\n")

    if order["CoherentPeak"] is not None :
        MCconfig_file.write("COHERENT_PEAK="+str(order["CoherentPeak"])+"\n")

    if str(order["Generator"]) == "file:":
        if foundConfig == "True":
            MCconfig_file.write("GENERATOR="+str(order["Generator"])+"/"+str(order["Generator_Config"])+"\n")
        else:
            MCconfig_file.write("GENERATOR="+str(order["Generator"])+"/"+foundConfig+"\n")
    else:
        MCconfig_file.write("GENERATOR="+str(order["Generator"])+"\n")
        if foundConfig=="True":
            MCconfig_file.write("GENERATOR_CONFIG="+str(order["Generator_Config"])+"\n")
        else:
            MCconfig_file.write("GENERATOR_CONFIG="+foundConfig+"\n")

    MCconfig_file.write("GEANT_VERSION="+str(order["GeantVersion"])+"\n")
    MCconfig_file.write("NOSECONDARIES="+str(abs(order["GeantSecondaries"]-1))+"\n")
    MCconfig_file.write("BKG="+str(order["BKG"])+"\n")
    splitLoc=str(order["OutputLocation"]).split("/")
    outputstring="/".join(splitLoc[7:-1])
    #order["OutputLocation"]).split("/")[7]
    MCconfig_file.write("DATA_OUTPUT_BASE_DIR=/osgpool/halld/tbritton/REQUESTEDMC_OUTPUT/"+str(outputstring)+"\n")
    #print "FOUND CONFIG="+foundConfig

    if(order["RCDBQuery"] != ""):
        MCconfig_file.write("RCDB_QUERY="+order["RCDBQuery"]+"\n")

    if(order["ReactionLines"] != ""):
        jana_config_file=open("/osgpool/halld/tbritton/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config","w")
        janaplugins="PLUGINS danarest,monitoring_hists,mcthrown_tree"
        if(order["ReactionLines"]):
            janaplugins+=",ReactionFilter\n"+order["ReactionLines"]
        else:
            janaplugins+="\n"
        jana_config_file.write(janaplugins)
        jana_config_file.close()
        MCconfig_file.write("CUSTOM_PLUGINS=file:/osgpool/halld/tbritton/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config\n")

    
    MCconfig_file.write("ENVIRONMENT_FILE=/group/halld/www/halldweb/html/dist/"+str(order["VersionSet"])+"\n")
    MCconfig_file.close()

def SubmitList(SubList,job_IDs_submitted):
    for row in SubList:
        print row
                
        if row['ID'] in job_IDs_submitted:
            continue

        projinfo_q="SELECT * FROM Project where ID="+str(row['Project_ID'])
        curs.execute(projinfo_q) 
        proj=curs.fetchall()
        #print proj
        RunNumber=str(proj[0]["RunNumLow"])
        if proj[0]["RunNumLow"] != proj[0]["RunNumHigh"] :
            RunNumber = RunNumber + "-" + str(proj[0]["RunNumHigh"])

        cleangen=1
        if proj[0]["SaveGeneration"]==1:
            cleangen=0

        cleangeant=1
        if proj[0]["SaveGeant"]==1:
            cleangeant=0
    
        cleansmear=1
        if proj[0]["SaveSmear"]==1:
            cleansmear=0
    
        cleanrecon=1
        if proj[0]["SaveReconstruction"]==1:
            cleanrecon=0

        status = subprocess.call("cp /osgpool/halld/tbritton/gluex_MCwrapper/examples/OSGShell.config ./MCDispatched.config", shell=True)
        WritePayloadConfig(proj[0],"True")

        command="/osgpool/halld/tbritton/gluex_MCwrapper/gluex_MC.py MCDispatched.config "+str(RunNumber)+" "+str(row["NumEvts"])+" per_file=20000 base_file_number="+str(row["FileNumber"])+" generate="+str(proj[0]["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(proj[0]["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(proj[0]["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(proj[0]["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid=-"+str(row['ID'])+" logdir=/osgpool/halld/tbritton/REQUESTEDMC_LOGS/"+proj[0]["OutputLocation"].split("/")[7]+" batch=1 submitter=1"
        print command
        status = subprocess.call(command, shell=True)

        job_IDs_submitted.append(row['ID'])

def main(argv):
    #print(argv)

    Block_size=10
    int_i=0
    more_sub=True
    rows=[]
    if(os.path.isfile("/osgpool/halld/tbritton/.ALLSTOP")==True):
        print "ALL STOP DETECTED"
        exit(1)

    numprocesses_running=subprocess.check_output(["echo `ps all -u tbritton | grep MCSubmitter.py | grep -v grep | wc -l`"], shell=True)
    #print(args)

    job_IDs_submitted=[]

    if(int(numprocesses_running) <5):
        curs.execute("INSERT INTO MCSubmitter (Host,StartTime,Status) VALUES ('"+str(socket.gethostname())+"', NOW(), 'Running' )")
        conn.commit()
        querysubmitters="SELECT MAX(ID) FROM MCSubmitter;"
        curs.execute(querysubmitters)
        lastid = curs.fetchall()
        try:    
            while more_sub:
                rows=[]
                int_i=0
                print "============================================================="
                query = "SELECT UName,FileNumber,Tested,NumEvts,Notified,Jobs.ID,Project_ID,Priority from Jobs,Project,Users where Tested=1 && Notified is NULL && Jobs.ID not in (Select Job_ID from Attempts) and Project_ID = Project.ID and Uname = name order by Priority desc limit "+str(Block_size)
                if(Block_size==1):
                    query = "SELECT UName,FileNumber,Tested,NumEvts,Notified,Jobs.ID,Project_ID,Priority from Jobs,Project,Users where Tested=1 && Notified is NULL && Jobs.ID not in (Select Job_ID from Attempts) and Project_ID = Project.ID and Uname = name order by Priority desc"

                print query
                curs.execute(query) 
                rows=curs.fetchall()

                print("length of rows: "+str(len(rows)))

                if(len(rows)==0):
                    more_sub=False
                    break

                SubmitList(rows,job_IDs_submitted)
                #Must do the following commit even through gluex_MC.py does one.  Else the above query is cached and does not update properly
                conn.commit()
            curs.execute("UPDATE MCSubmitter SET EndTime=NOW(), Status=\"Success\" where ID="+str(lastid[0]["MAX(ID)"]))
            conn.commit()
        except:
            curs.execute("UPDATE MCSubmitter SET Status=\"Fail\" where ID="+str(lastid[0]["MAX(ID)"]))
            conn.commit()
            pass
    conn.close()
        

if __name__ == "__main__":
   main(sys.argv[1:])
