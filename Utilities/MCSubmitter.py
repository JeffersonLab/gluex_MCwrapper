#!/usr/bin/env python3
import MySQLdb
import sys
import datetime
import time
import os.path
from optparse import OptionParser
import subprocess
from subprocess import call
from subprocess import Popen, PIPE
import socket
import pprint
import pwd



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

runner_name=pwd.getpwuid( os.getuid() )[0]

if( not (runner_name=="tbritton" or runner_name=="mcwrap")):
    print("ERROR: You must be tbritton or mcwrap to run this script")
    sys.exit(1)

def WritePayloadConfig(order,foundConfig,batch_system):
    
    MCconfig_file= open("MCSubDispatched.config","a")
    MCconfig_file.write("PROJECT="+str(order["Exp"])+"\n")

    if str(order["Exp"]) == "CPP":
        MCconfig_file.write("VARIATION=mc_cpp"+"\n")
        MCconfig_file.write("FLUX_TO_GEN=cobrems"+"\n")

    splitlist=order["OutputLocation"].split("/")
    MCconfig_file.write("WORKFLOW_NAME=proj"+str(order["ID"])+"_"+splitlist[len(splitlist)-2]+"\n")
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

    if str(order["GenFlux"]) == "cobrems":
        MCconfig_file.write("FLUX_TO_GEN=cobrems"+"\n")

    if order["CoherentPeak"] is not None :
        MCconfig_file.write("COHERENT_PEAK="+str(order["CoherentPeak"])+"\n")

    if str(order["Generator"]) == "file:":
        if batch_system == "OSG":
            MCconfig_file.write("GENERATOR="+str(order["Generator"])+"/"+str(order["Generator_Config"])+"\n")
        elif batch_system == "SWIF":
            location=order["Generator_Config"].replace("/osgpool/halld/"+runner_name+"/","/work/halld/home/"+runner_name+"/")
            scp_order="scp "+str(order["Generator_Config"])+" ifarm:"+location
            print("COPYING GENERATOR file")
            print(scp_order)
            subprocess.call(scp_order,shell=True)
            MCconfig_file.write("GENERATOR="+str(order["Generator"])+"/"+str(location)+"\n")
    else:
        MCconfig_file.write("GENERATOR="+str(order["Generator"])+"\n")
        if batch_system == "OSG":
            MCconfig_file.write("GENERATOR_CONFIG="+str(order["Generator_Config"])+"\n")
        elif batch_system == "SWIF":
            location=order["Generator_Config"].replace("/osgpool/halld/"+runner_name+"/","/work/halld/home/"+runner_name+"/")
            scp_order="scp "+str(order["Generator_Config"])+" ifarm:"+location
            print("COPYING GENERATOR CONFIG")
            print(scp_order)
            subprocess.call(scp_order,shell=True)
            MCconfig_file.write("GENERATOR_CONFIG="+str(location)+"\n")

    if order["GenPostProcessing"] != None and order["GenPostProcessing"] != "":
        MCconfig_file.write("GENERATOR_POSTPROCESS="+str(order["GenPostProcessing"])+"\n")

    MCconfig_file.write("GEANT_VERSION="+str(order["GeantVersion"])+"\n")
    MCconfig_file.write("NOSECONDARIES="+str(abs(order["GeantSecondaries"]-1))+"\n")
    MCconfig_file.write("BKG="+str(order["BKG"])+"\n")
    splitLoc=str(order["OutputLocation"]).split("/")
    outputstring="/".join(splitLoc[7:-1])
    #order["OutputLocation"]).split("/")[7]
    if batch_system == "OSG":
        MCconfig_file.write("DATA_OUTPUT_BASE_DIR=/osgpool/halld/"+runner_name+"/REQUESTEDMC_OUTPUT/"+str(outputstring)+"\n")
    elif batch_system == "SWIF":
        MCconfig_file.write("DATA_OUTPUT_BASE_DIR=/cache/halld/gluex_simulations/REQUESTED_MC/"+str(outputstring)+"\n")
    #print "FOUND CONFIG="+foundConfig

    if(order["RCDBQuery"] != ""):
        MCconfig_file.write("RCDB_QUERY="+order["RCDBQuery"]+"\n")

    if(order["ReactionLines"] != ""):
        if(order["ReactionLines"][0:5] != "file:"):
            jana_config_file=open("/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config","w")
            janaplugins="PLUGINS danarest,monitoring_hists,mcthrown_tree"
            if(order["ReactionLines"]):
                janaplugins+=",ReactionFilter\n"+order["ReactionLines"]
            else:
                janaplugins+="\n"
            jana_config_file.write(janaplugins)
            jana_config_file.close()


        if batch_system == "OSG":
            MCconfig_file.write("CUSTOM_PLUGINS=file:/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config\n")
        elif batch_system == "SWIF":
            scp_jana = "scp "+"/osgpool/halld/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config ifarm:"+"/work/halld/home/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config"
            print(scp_jana)
            subprocess.call(scp_jana,shell=True)
            MCconfig_file.write("CUSTOM_PLUGINS=file:/work/halld/home/"+runner_name+"/REQUESTEDMC_CONFIGS/"+str(order["ID"])+"_jana.config\n")


    MCconfig_file.write("ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/"+str(order["VersionSet"])+"\n")
    if(order["ANAVersionSet"] != None and order["ANAVersionSet"] != "None" ):
        MCconfig_file.write("ANA_ENVIRONMENT_FILE=/group/halld/www/halldweb/html/halld_versions/"+str(order["ANAVersionSet"])+"\n")
    MCconfig_file.close()

def SubmitList(SubList,job_IDs_submitted):
    print("Submitting SubList")
    row_index=0
    list_to_Submit=list(SubList)
    #print("element 0 is "+str(list_to_Submit[0]))
    print("Submitting >= "+str(len(list_to_Submit))+" jobs")
    while row_index < len(list_to_Submit):
        print("on row "+str(row_index),"out of",str(len(list_to_Submit)))
    #for row in SubList:
        #print("Row",row)
        row=list_to_Submit[row_index]
        #print("checking for already submitted")
        if row['ID'] in job_IDs_submitted:
            print("Job "+str(row['ID'])+" already submitted")
            row_index+=1
            continue
        #print("job not already submitted")
        #get freespace on node
        space_cmd="df -H | grep /osgpool/halld"
        #print(space_cmd)
        cmd=subprocess.Popen(space_cmd,shell=True,stdout=PIPE,stderr=PIPE)
        #print("communicating")
        out, err = cmd.communicate()
        #print("communicated")
        #print(out.split()[4])
        percent_full=float(str(out.split()[4],"utf-8").strip("%"))
        print("percent full is "+str(percent_full))
        if percent_full > 75.0:
            print("Node is too full to submit new jobs")
            return
        
        print("about to bundle")
        bundled=False
        bundle_query="select ID,FileNumber from Jobs where Project_ID in (SELECT Project_ID from Jobs where ID="+str(row['ID'])+") and RunNumber in (SELECT RunNumber from Jobs where ID="+str(row['ID'])+") and NumEvts in (SELECT NumEvts from Jobs where ID="+str(row['ID'])+") and IsActive=1;"
        curs.execute(bundle_query)
        alljobs = curs.fetchall()

        print("bundled:",len(alljobs))
        if(len(alljobs)>1):
            bundled=True
            
        projinfo_q="SELECT * FROM Project where ID="+str(row['Project_ID'])
        curs.execute(projinfo_q) 
        proj=curs.fetchall()
        #print proj
        RunNumber=row["RunNumber"]

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

        system_to_run_on=decideSystem(row)

        MCWRAPPER_BOT_HOME="/scigroup/mcwrapper/gluex_MCwrapper/"
        if system_to_run_on == "OSG":
            status = subprocess.call("cp "+MCWRAPPER_BOT_HOME+"/examples/OSGShell.config ./MCSubDispatched.config", shell=True)
        elif system_to_run_on == "SWIF":
            status = subprocess.call("cp "+MCWRAPPER_BOT_HOME+"examples/SWIFShell.config ./MCSubDispatched.config", shell=True)

        WritePayloadConfig(proj[0],"True",system_to_run_on)

        per_file_num=20000
        get_perfile_q="SELECT PerFile from Generator_perfiles where GenName=\""+str(proj[0]["Generator"])+"\";"
        curs.execute(get_perfile_q) 
        genrow=curs.fetchall()
        try:
            per_file_num=genrow[0]["PerFile"]
        except Exception as e:
            print(e)
            pass

        
        command=MCWRAPPER_BOT_HOME+"/gluex_MC.py MCSubDispatched.config "+str(RunNumber)+" "+str(row["NumEvts"])+" per_file="+str(per_file_num)+" base_file_number="+str(row["FileNumber"])+" generate="+str(proj[0]["RunGeneration"])+" cleangenerate="+str(cleangen)+" geant="+str(proj[0]["RunGeant"])+" cleangeant="+str(cleangeant)+" mcsmear="+str(proj[0]["RunSmear"])+" cleanmcsmear="+str(cleansmear)+" recon="+str(proj[0]["RunReconstruction"])+" cleanrecon="+str(cleanrecon)+" projid=-"+str(row['ID'])+" logdir=/osgpool/halld/"+runner_name+"/REQUESTEDMC_LOGS/"+proj[0]["OutputLocation"].split("/")[7]+" batch=2 submitter=1 tobundle=1"
        print(command)
        #status = subprocess.call("printenv > /tmp/Submitter_env")
        status = subprocess.call(command, shell=True)

        for job in alljobs:
            job_IDs_submitted.append(job['ID'])
        
        print("Submitted",job_IDs_submitted)
        
        #remove all jobs from list in bundle
        copy_of_list_to_Submit=list_to_Submit.copy()
        print("length of list to submit",len(copy_of_list_to_Submit))
        iter_index=0
        for job in copy_of_list_to_Submit:
            #print("on index",iter_index)
            #print("job",job)
            if job['ID'] in job_IDs_submitted:
                #print(list_to_Submit.index(job))
                index=list_to_Submit.index(job)
                #print("removing",index)
                list_to_Submit.pop(index)
                row_index=-1
                #SubList.remove(job)
            #else:
            #    print(iter_index,"not in list")
            #print("modifying indexes")
            iter_index+=1
            
            #print("done modifying indexes")

        #exit(1)
        row_index+=1
        #if(bundled):
        #    break

def decideSystem(row):

    return "OSG"
    command="condor_q | grep 'Total for mcwrap'" #"condor_q | grep tbritton"
    print(command)
    jobSubout=""
    try:
        jobSubout=subprocess.check_output(command,shell=True)
    except:
        return "OSG"

    print("job Sub:",str(jobSubout,'utf-8'))

    rows=str(jobSubout,'utf-8').split("\n")
    rows=rows[:-1]
    print(rows)
    running=0.
    idle=0.
    print(len(rows))
    for row in rows:
        condor_q_vals=row.split()
        if(len(condor_q_vals) <5):
            continue
        print(str(condor_q_vals[11])+"  |  "+str(condor_q_vals[9]))
        if(str(condor_q_vals[11]) != "_"): #old: 6
            running=running+int(condor_q_vals[11]) #old: 6
            print("running: "+str(running))
       
        if(condor_q_vals[9] != "_"): #old: 7
            idle=idle+int(condor_q_vals[9]) #old: 7
            print("idle: "+str(idle))

    print("Running")
    print(running)
    print("Idle")
    print(idle)
    print("SUM")

    osg_sum=int(running)+int(idle)
    if(running==0):
        running=1
    osg_ratio=float(idle)/float(running)
    print(osg_sum)
    print(osg_ratio)
    
    if osg_sum > 3000 and osg_ratio > 2.0:
        print("SWIF")
        return "OSG"
    else:
        print("OSG")
        return "OSG"


def main(argv):
    #print(argv)

    Block_size=1000
    int_i=0
    more_sub=True
    rows=[]
    if(os.path.isfile("/osgpool/halld/"+runner_name+"/.ALLSTOP")==True):
        print("ALL STOP DETECTED")
        exit(1)

    numprocesses_running=subprocess.check_output(["echo `ps all -u "+runner_name+" | grep MCSubmitter.py | grep -v grep | wc -l`"], shell=True)
    #print(args)

    job_IDs_submitted=[]
    print(numprocesses_running)
    if(int(numprocesses_running) <3):
        try:
            curs.execute("INSERT INTO MCSubmitter (Host,StartTime,Status) VALUES ('"+str(socket.gethostname())+"', NOW(), 'Running' )")
            conn.commit()
        except Exception as e:
            print(e)
            pass

        querysubmitters="SELECT MAX(ID) FROM MCSubmitter;"
        curs.execute(querysubmitters)
        lastid = curs.fetchall()
        try:    
            while more_sub:# and int_i<1:
                #sleep 1 second
                #time.sleep(1)
                
                rows=[]
                int_i+=1
                print("=============================================================")
                query="SELECT UName, RunNumber, FileNumber, Tested, NumEvts, BKG, Notified, Jobs.ID, Project_ID, Priority, IsActive FROM Jobs INNER JOIN Project ON Jobs.Project_ID = Project.ID INNER JOIN Users ON Project.user_id = Users.id LEFT JOIN Attempts ON Jobs.ID = Attempts.Job_ID WHERE Tested = 1 AND Notified IS NULL AND IsActive = 1 AND Attempts.Job_ID IS NULL ORDER BY Priority DESC LIMIT "+str(Block_size)+";"
                #query="SELECT UName,RunNumber,FileNumber,Tested,NumEvts,BKG,Notified,Jobs.ID,Project_ID,Priority,IsActive from Jobs,Project,Users where Tested=1 && Notified is NULL && IsActive=1 && Jobs.ID not in (Select Job_ID from Attempts) and Project_ID = Project.ID and Users.id = Project.user_id order by Priority desc limit "+str(Block_size)+";"
                #query = "SELECT UName,RunNumber,FileNumber,Tested,NumEvts,BKG,Notified,Jobs.ID,Project_ID,Priority,IsActive from Jobs,Project,Users where Tested=1 && Notified is NULL && IsActive=1 && Jobs.ID not in (Select Job_ID from Attempts) and Project_ID = Project.ID and Users.id = Project.user_id order by Priority desc limit "+str(Block_size)
                if(Block_size==1):
                    query ="SELECT UName, RunNumber, FileNumber, Tested, NumEvts, BKG, Notified, Jobs.ID, Project_ID, Priority, IsActive FROM Jobs INNER JOIN Project ON Jobs.Project_ID = Project.ID INNER JOIN Users ON Project.user_id = Users.id LEFT JOIN Attempts ON Jobs.ID = Attempts.Job_ID WHERE Tested = 1 AND Notified IS NULL AND IsActive = 1 AND Attempts.Job_ID IS NULL ORDER BY Priority DESC;"

                
                print("Query:", query)
                curs.execute(query) 
                rows=curs.fetchall()
                #lrows=list(rows)
                print("length of rows: "+str(len(rows)))

                #for row in lrows:
                #    bkg_parts=row["BKG"].split(":")
                #    if bkg_parts[0] == "Random":
                #        formatted_runnum="%06d" % row["RunNumber"]
                #        path_to_check="/osgpool/halld/random_triggers/"+str(bkg_parts[1])+"/run"+str(formatted_runnum)+"_random.hddm"
                #        if not os.path.isfile(path_to_check):
                #            jobdeactivate="UPDATE Jobs Set IsActive=0 where ID="+str(row["Jobs.ID"])
                #            print(jobdeactivate)
                #            curs.execute(jobdeactivate)
                #            conn.commit()
                #            lrows.remove(row)

                if(len(rows)==0):
                    more_sub=False
                    break


                SubmitList(rows,job_IDs_submitted)
                #Must do the following commit even through gluex_MC.py does one.  Else the above query is cached and does not update properly
                conn.commit()
            try:
                curs.execute("UPDATE MCSubmitter SET EndTime=NOW(), Status=\"Success\" where ID="+str(lastid[0]["MAX(ID)"]))
                conn.commit()
            except Exception as e:
                print(e)
                pass
        except Exception as e:
            print("exception")
            print(e)
            curs.execute("UPDATE MCSubmitter SET Status=\"Fail\" where ID="+str(lastid[0]["MAX(ID)"]))
            conn.commit()
            pass
    conn.close()
        

if __name__ == "__main__":
   main(sys.argv[1:])
