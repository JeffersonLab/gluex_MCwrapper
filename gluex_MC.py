#!/usr/bin/env python2
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
from os import environ
from optparse import OptionParser
import os.path
import rcdb
import ccdb
from ccdb.cmd.console_context import ConsoleContext
import ccdb.path_utils
from ccdb import Directory, TypeTable, Assignment, ConstantSet
from array import array
from datetime import datetime
import mysql.connector
import time
import os
import getpass
import sys
import re
import subprocess
from subprocess import call
import glob
import hddm_s
import socket
try:
        dbcnx = mysql.connector.connect(user='mcuser', database='gluex_mc', host='hallddb.jlab.org')
        dbcursor = dbcnx.cursor()
except:
        pass

MCWRAPPER_VERSION="2.9.0"
MCWRAPPER_DATE="06/07/24"

#group sync test
#====================================================
#Takes in a few pertinant pieces of info.  Creates (if needed) a swif workflow and adds a job to it.
#if project ID is less than 0 its an attempt ID and is recorded as such
#if project ID is greater than 0 then it is a project ID and this call is going to record a new job (NOT ACTUALLY MAKING THE ATTEMPT)
#if project ID == 0 then it is neither and just scrape the batch_ID....do nothing.  Note: this scheme requires the first id in the tables to be 1 and not 0)
#====================================================
def BundleJob(job_id):
        bundle_query="select ID,FileNumber from Jobs where Project_ID in (SELECT Project_ID from Jobs where ID="+str(job_id)+") and RunNumber in (SELECT RunNumber from Jobs where ID="+str(job_id)+") and NumEvts in (SELECT NumEvts from Jobs where ID="+str(job_id)+") and IsActive=1;"
        dbcursor.execute(bundle_query)
        alljobs = dbcursor.fetchall()
        print("count:",len(alljobs))
        print(alljobs)
        return alljobs

#====================================================
#simple function to email Project owner that their requested Project contains no events and set the Project.Tested to -2
#====================================================
def email_no_events(PROJECT_ID):
        email_query="select Email from Projects where ID="+str(PROJECT_ID)+";"
        dbcursor.execute(email_query)
        allemails = dbcursor.fetchall()
        if len(allemails)==1:
                Project_update_q="update Projects set Tested=-2 where ID="+str(PROJECT_ID)+";"
                dbcursor.execute(Project_update_q)
                dbcnx.commit()


def swif_add_job(WORKFLOW, RUNNO, FILENO,SCRIPT,COMMAND, VERBOSE,PROJECT,TRACK,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR, PROJECT_ID):
        STUBNAME=""
        if(COMMAND['custom_tag_string'] != "I_dont_have_one"):
                STUBNAME=COMMAND['custom_tag_string']+"_"
        # PREPARE NAMES
        STUBNAME = STUBNAME+str(RUNNO) + "_" + str(FILENO)

        JOBNAME = WORKFLOW + "_" + STUBNAME

        # CREATE ADD-JOB COMMAND
        # job
        #try removing the name specification

        mkdircom="mkdir -p "+DATA_OUTPUT_BASE_DIR+"/log/"
        status = subprocess.call(mkdircom, shell=True)


        add_command = "swif add-job -workflow " + WORKFLOW #+ " -name " + JOBNAME
        # project/track
        add_command += " -project " + PROJECT + " -track " + TRACK
        # resources
        add_command += " -create -cores " + NCORES + " -disk " + DISK + " -ram " + RAM + " -time " + TIMELIMIT + " -os " + OS
        # stdout
        add_command += " -stdout " + DATA_OUTPUT_BASE_DIR + "/log/" + str(RUNNO) + "_stdout." + STUBNAME + ".out"
        # stderr
        add_command += " -stderr " + DATA_OUTPUT_BASE_DIR + "/log/" + str(RUNNO) + "_stderr." + STUBNAME + ".err"
        # tags
        add_command += " -tag run_number " + str(RUNNO)
        # tags
        add_command += " -tag file_number " + str(FILENO)
        # script with options command
        add_command += " -fail-save-dir "+DATA_OUTPUT_BASE_DIR

        add_command += " "+SCRIPT  +" "+ getCommandString(COMMAND,"SWIF")

        if(VERBOSE == True):
                print( "job add command is \n" + str(add_command))

        if(int(NCORES)==1 and int(RAM[:-2]) >= 10 and RAM[-2:]=="GB" ):
                print( "SciComp has a limit on RAM requested per thread, as RAM is the limiting factor.")
                print( "This will likely cause an AUGER-SUBMIT error.")
                print( "Please either increase NCORES or decrease RAM requested and try again.")
                exit(1)
        # ADD JOB
        if add_command.find(';')!=-1 or add_command.find('&')!=-1 :#THIS CHECK HELPS PROTECT AGAINST A POTENTIAL HACK VIA CONFIG FILES
                print( "Nice try.....you cannot use ; or &")
                exit(1)
        #status = subprocess.call(add_command.split(" "))
        SWIF_ID_NUM="-1"

        if( int(PROJECT_ID) <=0 ):
                print(add_command)
                jobSubout=subprocess.check_output(add_command.split(" "))
                print(jobSubout)
                idnumline=jobSubout.split("\n")[0].strip().split("=")

                if(len(idnumline) == 2 ):
                        SWIF_ID_NUM=str(idnumline[1])

        if int(PROJECT_ID) > 0:
                recordJob(PROJECT_ID,RUNNO,FILENO,SWIF_ID_NUM,COMMAND['num_events'])
                #recordFirstAttempt(PROJECT_ID,RUNNO,FILENO,"SWIF",SWIF_ID_NUM,COMMAND['num_events'],NCORES,RAM)
        elif int(PROJECT_ID) < 0:
                recordAttempt(abs(int(PROJECT_ID)),RUNNO,FILENO,"SWIF",SWIF_ID_NUM,COMMAND['num_events'],NCORES,RAM)

def swif2_add_job(WORKFLOW, RUNNO, FILENO,SCRIPT,COMMAND, VERBOSE,ACCOUNT,PARTITION,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR,LOG_DIR, PROJECT_ID):
        STUBNAME=""
        if(COMMAND['custom_tag_string'] != "I_dont_have_one"):
                STUBNAME=COMMAND['custom_tag_string']+"_"
        # PREPARE NAMES
        STUBNAME = STUBNAME+str(RUNNO) + "_" + str(FILENO)

        JOBNAME = WORKFLOW + "_" + STUBNAME

        # CREATE ADD-JOB COMMAND
        # job
        #try removing the name specification

        mkdircom="mkdir -p "+LOG_DIR+"/log/"
        status = subprocess.call(mkdircom, shell=True)


        add_command = "swif2 add-job -workflow " + WORKFLOW #+ " -name " + JOBNAME
        # account/partition (used to be project/track in swif)
        add_command += " -account " + ACCOUNT + " -partition " + PARTITION
        # resources
        add_command += " -create -cores " + NCORES + " -disk " + DISK + " -ram " + RAM + " -time " + TIMELIMIT + " -os " + OS
        # stdout
        add_command += " -stdout " + LOG_DIR + "/log/" + str(RUNNO) + "_stdout." + STUBNAME + ".out"
        # stderr
        add_command += " -stderr " + LOG_DIR + "/log/" + str(RUNNO) + "_stderr." + STUBNAME + ".err"
        # tags
        add_command += " -tag run_number " + str(RUNNO)
        # tags
        add_command += " -tag file_number " + str(FILENO)
        # script with options command
        # add_command += " -fail-save-dir "+DATA_OUTPUT_BASE_DIR

        add_command += " "+SCRIPT  +" "+ getCommandString(COMMAND,"SWIF")

        if(VERBOSE == True):
                print( "job add command is \n" + str(add_command))

        if(int(NCORES)==1 and int(RAM[:-2]) >= 10 and RAM[-2:]=="GB" ):
                print( "SciComp has a limit on RAM requested per thread, as RAM is the limiting factor.")
                print( "This will likely cause an AUGER-SUBMIT error.")
                print( "Please either increase NCORES or decrease RAM requested and try again.")
                exit(1)
        # ADD JOB
        if add_command.find(';')!=-1 or add_command.find('&')!=-1 :#THIS CHECK HELPS PROTECT AGAINST A POTENTIAL HACK VIA CONFIG FILES
                print( "Nice try.....you cannot use ; or &")
                exit(1)
        #status = subprocess.call(add_command.split(" "))
        SWIF_ID_NUM="-1"

        if( int(PROJECT_ID) <=0 ):
                print(add_command)
                jobSubout=subprocess.check_output(add_command.split(" "))
                print(jobSubout)
                idnumline=jobSubout.split("\n")[0].strip().split("=")

                if(len(idnumline) == 2 ):
                        SWIF_ID_NUM=str(idnumline[1])

        if int(PROJECT_ID) > 0:
                recordJob(PROJECT_ID,RUNNO,FILENO,SWIF_ID_NUM,COMMAND['num_events'])
                #recordFirstAttempt(PROJECT_ID,RUNNO,FILENO,"SWIF",SWIF_ID_NUM,COMMAND['num_events'],NCORES,RAM)
        elif int(PROJECT_ID) < 0:
                recordAttempt(abs(int(PROJECT_ID)),RUNNO,FILENO,"SWIF",SWIF_ID_NUM,COMMAND['num_events'],NCORES,RAM)


def swif2cont_add_job(WORKFLOW, RUNNO, FILENO,SCRIPT,COMMAND, VERBOSE,ACCOUNT,PARTITION,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR,LOG_DIR, PROJECT_ID):
        STUBNAME=""
        if(COMMAND['custom_tag_string'] != "I_dont_have_one"):
                STUBNAME=COMMAND['custom_tag_string']+"_"
        # PREPARE NAMES
        STUBNAME = STUBNAME+str(RUNNO) + "_" + str(FILENO)

        JOBNAME = WORKFLOW + "_" + STUBNAME

        # CREATE ADD-JOB COMMAND
        # job
        #try removing the name specification

        mkdircom="mkdir -p "+LOG_DIR+"/log/"
        status = subprocess.call(mkdircom, shell=True)


        add_command = "swif2 add-job -workflow " + WORKFLOW #+ " -name " + JOBNAME
        # account/partition (used to be project/track in swif)
        add_command += " -account " + ACCOUNT + " -partition " + PARTITION
        # resources
        add_command += " -create -cores " + NCORES + " -disk " + DISK + " -ram " + RAM + " -time " + TIMELIMIT + " -os " + OS
        # stdout
        add_command += " -stdout " + LOG_DIR + "/log/" + str(RUNNO) + "_stdout." + STUBNAME + ".out"
        # stderr
        add_command += " -stderr " + LOG_DIR + "/log/" + str(RUNNO) + "_stderr." + STUBNAME + ".err"
        # tags
        add_command += " -tag run_number " + str(RUNNO)
        # tags
        add_command += " -tag file_number " + str(FILENO)
        # script with options command
        # add_command += " -fail-save-dir "+DATA_OUTPUT_BASE_DIR

        add_command += " singularity exec --bind /scigroup/mcwrapper/ --bind /u --bind /group/halld/ --bind /scratch/slurm/ --bind /lustre/enp/swif2 --bind /cvmfs --bind /work/osgpool/ --bind /work/halld --bind /cache/halld --bind /volatile/halld --bind /work/halld2 /cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_prod:v1 "+os.environ.get('MCWRAPPER_CENTRAL')+"/MakeMC.sh "+getCommandString(COMMAND,"SWIF")
        # print(getCommandString(COMMAND,"SBATCH_SLURM"))
        # add_command += " "+SCRIPT  +" "+ getCommandString(COMMAND,"SWIF")

        if(VERBOSE == True):
                print( "job add command is \n" + str(add_command))

        if(int(NCORES)==1 and int(RAM[:-2]) >= 10 and RAM[-2:]=="GB" ):
                print( "SciComp has a limit on RAM requested per thread, as RAM is the limiting factor.")
                print( "This will likely cause an AUGER-SUBMIT error.")
                print( "Please either increase NCORES or decrease RAM requested and try again.")
                exit(1)
        # ADD JOB
        if add_command.find(';')!=-1 or add_command.find('&')!=-1 :#THIS CHECK HELPS PROTECT AGAINST A POTENTIAL HACK VIA CONFIG FILES
                print( "Nice try.....you cannot use ; or &")
                exit(1)
        #status = subprocess.call(add_command.split(" "))
        SWIF_ID_NUM="-1"

        if( int(PROJECT_ID) <=0 ):
                print(add_command)
                jobSubout=subprocess.check_output(add_command.split(" "))
                print(jobSubout)
                idnumline=jobSubout.split("\n")[0].strip().split("=")

                if(len(idnumline) == 2 ):
                        SWIF_ID_NUM=str(idnumline[1])

        if int(PROJECT_ID) > 0:
                recordJob(PROJECT_ID,RUNNO,FILENO,SWIF_ID_NUM,COMMAND['num_events'])
                #recordFirstAttempt(PROJECT_ID,RUNNO,FILENO,"SWIF",SWIF_ID_NUM,COMMAND['num_events'],NCORES,RAM)
        elif int(PROJECT_ID) < 0:
                recordAttempt(abs(int(PROJECT_ID)),RUNNO,FILENO,"SWIF",SWIF_ID_NUM,COMMAND['num_events'],NCORES,RAM)


#====================================================
#Takes in a few pertinant pieces of info and submits a job to qsub.  This has not been fully integrated into the autonomous side
#missing the batch_ID scraping. And  missing better host recording (Stubbed as "QSUB" for now)
#====================================================
def  qsub_add_job(VERBOSE, WORKFLOW, RUNNUM, FILENUM, SCRIPT_TO_RUN, COMMAND, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, MEMLIMIT, QUEUENAME, LOG_DIR, PROJECT_ID ):
        #name
        STUBNAME=""
        if(COMMAND['custom_tag_string'] != "I_dont_have_one"):
                STUBNAME=COMMAND['custom_tag_string']+"_"
        # PREPARE NAMES
        STUBNAME = STUBNAME+str(RUNNUM) + "_" + str(FILENO)

        JOBNAME = WORKFLOW + "_" + STUBNAME

        sub_command="qsub MCqsub.submit"

        qsub_ml_command=""
        bits=NCORES.split(":")
        if (len(bits)==3):
                qsub_ml_command ="nodes="+bits[0]+":"+bits[1]+":ppn="+bits[2]
        elif (len(bits)==2):
                qsub_ml_command ="nodes="+bits[0]+":ppn="+bits[1]

        shell_to_use="/bin/bash"
        if (SCRIPT_TO_RUN[len(SCRIPT_TO_RUN)-3]=='c'):
                shell_to_use="/bin/csh"


        if( ".iu.edu" in socket.gethostname() and QUEUENAME.upper() == "STANLEY"):
                f=open('MCqsub.submit','w')
                f.write("#$ -o "+LOG_DIR+"/log/"+JOBNAME+".out"+"\n" )
                f.write("#$ -N "+JOBNAME+"\n" )
                f.write("#$ -j y\n" )
                f.write(shell_to_use+indir+" "+COMMAND+"\n" )
                f.write("exit 0\n")
                f.close()
        else:
                f=open('MCqsub.submit','w')
                f.write("#!/bin/sh -f"+"\n" )
                f.write("#PBS"+" -N "+JOBNAME+"\n" )
                f.write("#PBS"+" -l "+qsub_ml_command+"\n" )
                f.write("#PBS"+" -o "+LOG_DIR+"/log/"+JOBNAME+".out"+"\n" )
                f.write("#PBS"+" -e "+LOG_DIR+"/log/"+JOBNAME+".err"+"\n" )
                f.write("#PBS"+" -l walltime="+TIMELIMIT+"\n" )
                if (QUEUENAME != "DEF"):
                        f.write("#PBS"+" -q "+QUEUENAME+"\n" )
                f.write("#PBS"+" -l mem="+MEMLIMIT+"\n" )
                f.write("#PBS"+" -m a"+"\n" )
                f.write("#PBS"+" -p 0"+"\n" )
                f.write("#PBS -c c=2 \n")
                f.write("NCPU=\\ \n")
                f.write("NNODES=\\ \n")

                # f.write("trap \'\' 2 9 15 \n" )
                f.write(shell_to_use+" "+SCRIPT_TO_RUN+" "+getCommandString(COMMAND,"PBS")+"\n" )
                f.write("exit 0\n")
                f.close()

        time.sleep(0.25)

        if ( DATA_OUTPUT_BASE_DIR != LOG_DIR ) :
                status = subprocess.call("mkdir -p "+LOG_DIR+"/log/", shell=True)

        mkdircom="mkdir -p "+DATA_OUTPUT_BASE_DIR+"/log/"

        status = subprocess.call(mkdircom, shell=True)
        if( int(PROJECT_ID) <=0 ):

                status = subprocess.call(sub_command, shell=True)
                if ( VERBOSE == False ) :
                        status = subprocess.call("rm MCqsub.submit", shell=True)

                if int(PROJECT_ID) > 0:
                        recordJob(PROJECT_ID,RUNNO,FILENO,SWIF_ID_NUM,COMMAND['num_events'])
                        #recordFirstAttempt(PROJECT_ID,RUNNO,FILENO,"QSUB",SWIF_ID_NUM,COMMAND['num_events'],NCORES,MEMLIMIT)
                elif int(PROJECT_ID) < 0:
                        recordAttempt(abs(int(PROJECT_ID)),RUNNO,FILENO,"QSUB",SWIF_ID_NUM,COMMAND['num_events'],NCORES,MEMLIMIT)

#====================================================
#Takes in a few pertinant pieces of info.  Submits to condor
#this has not been fleshed out because of OSG integration.
#essentially take OSG_add_job and remove the OSG specific stuff (path remapping and + flags)
#====================================================
def  condor_add_job(VERBOSE, WORKFLOW, RUNNUM, FILENUM, SCRIPT_TO_RUN, COMMAND, NCORES,  DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, PROJECT_ID, CONDOR_MAGIC ):
        #print(CONDOR_MAGIC)
        STUBNAME=""
        if(COMMAND['custom_tag_string'] != "I_dont_have_one"):
                STUBNAME=COMMAND['custom_tag_string']+"_"
        # PREPARE NAMES
        STUBNAME = STUBNAME+str(RUNNUM) + "_" + str(FILENUM)
        JOBNAME = WORKFLOW + "_" + STUBNAME

        mkdircom="mkdir -p "+DATA_OUTPUT_BASE_DIR+"/log/"

        f=open('MCcondor.submit','w')
        f.write("Executable = "+SCRIPT_TO_RUN+"\n")
        f.write("Arguments  = "+getCommandString(COMMAND,"CONDOR")+"\n")
        f.write("Error      = "+DATA_OUTPUT_BASE_DIR+"/log/"+"error_"+JOBNAME+".log\n")
        f.write("Output      = "+DATA_OUTPUT_BASE_DIR+"/log/"+"out_"+JOBNAME+".log\n")
        f.write("Log = "+DATA_OUTPUT_BASE_DIR+"/log/"+"CONDOR_"+JOBNAME+".log\n")
        f.write("RequestCpus = "+NCORES+"\n")

        if CONDOR_MAGIC != []:
                for magic in CONDOR_MAGIC:
                        f.write(magic+"\n")

        f.write("Queue 1\n")
        f.close()

        JOBNAME=JOBNAME.replace(".","p")
        if( int(PROJECT_ID) <=0 ):
                add_command="condor_submit -batch-name "+WORKFLOW+" MCcondor.submit"
                if add_command.find(';')!=-1 or add_command.find('&')!=-1 or mkdircom.find(';')!=-1 or mkdircom.find('&')!=-1:#THIS CHECK HELPS PROTEXT AGAINST A POTENTIAL HACK VIA CONFIG FILES
                        print( "Nice try.....you cannot use ; or &")
                        exit(1)

                status = subprocess.call(mkdircom, shell=True)
                status = subprocess.call(add_command, shell=True)
                status = subprocess.call("rm MCcondor.submit", shell=True)

        if int(PROJECT_ID) > 0:
                recordJob(PROJECT_ID,RUNNO,FILENUM,SWIF_ID_NUM,COMMAND['num_events'])
                #recordFirstAttempt(PROJECT_ID,RUNNO,FILENO,"Condor",SWIF_ID_NUM,COMMAND['num_events'],NCORES,"UnSet")
        elif int(PROJECT_ID) < 0:
                recordAttempt(abs(int(PROJECT_ID)),RUNNO,FILENUM,"Condor",SWIF_ID_NUM,COMMAND['num_events'],NCORES,"UnSet")


#====================================================
#Takes in a few pertinant pieces of info.  Submits to the OSG
#This involves a lot of string manipulation first to remap the passed locations to /srv/
#if project ID is less than 0 its an attempt ID and is recorded as such
#if project ID is greater than 0 then it is a project ID and this call is going to record a new job (NOT ACTUALLY MAKING THE ATTEMPT)
#if project ID == 0 then it is neither and just scrape the batch_ID....do nothing.  Note: this scheme requires the first id in the tables to be 1 and not 0)
#====================================================
def  OSG_add_job(VERBOSE, WORKFLOW, RUNNUM, FILENUM, SCRIPT_TO_RUN, COMMAND, NCORES, RAM, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID,bundled ):
        
        ship_random_triggers=False
        STUBNAME=""
        if(COMMAND['custom_tag_string'] != "I_dont_have_one"):
                STUBNAME=COMMAND['custom_tag_string']+"_"
        # PREPARE NAMES
        STUBNAME = STUBNAME+str(RUNNUM)


        numJobsInBundle=1
        bundledJobs=[]
        #print("PROJID:",str(PROJECT_ID))
        #print("TO BUNDLE:",bundled)
        if(int(PROJECT_ID)<0 and bundled):

                bundledJobs=BundleJob(-1*int(PROJECT_ID))
                numJobsInBundle=len(bundledJobs)
        elif(int(PROJECT_ID)<0 and not bundled):
                bundledJobs=[[-1*int(PROJECT_ID),FILENUM]]
                numJobsInBundle=len(bundledJobs)

        #print("FOUND JOBS:",bundledJobs)
        #print("LENGTH: ",numJobsInBundle)
        if(numJobsInBundle==1):
                STUBNAME=STUBNAME+ "_" + str(FILENUM)
        else:
                STUBNAME=STUBNAME+ "_$(Process)"

        JOBNAME = WORKFLOW + "_" + STUBNAME

        mkdircom="mkdir -p "+DATA_OUTPUT_BASE_DIR+"/log/"

        indir_parts=SCRIPT_TO_RUN.split("/")
        script_to_use=indir_parts[len(indir_parts)-1]
        print(script_to_use)
        ENVFILE_parts=ENVFILE.split("/")
        envfile_to_source="./"+ENVFILE_parts[len(ENVFILE_parts)-1] #"/srv/"+ENVFILE_parts[len(ENVFILE_parts)-1]

        ANAENVFILE_parts=ANAENVFILE.split("/")
        if(len(ANAENVFILE_parts) != 1):
                anaenvfile_to_source="../"+ANAENVFILE_parts[len(ANAENVFILE_parts)-1] #"/srv/"+ANAENVFILE_parts[len(ANAENVFILE_parts)-1]

        COMMAND_parts=COMMAND#COMMAND.split(" ")

        COMMAND_parts['environment_file']=envfile_to_source

        COMMAND_parts['output_directory']="./"
        COMMAND_parts['running_directory']="./"

        #print(COMMAND_parts)
        additional_passins=""
        if COMMAND_parts['ana_environment_file'] != "no_Analysis_env":
                #print filegen_parts
                additional_passins+=COMMAND_parts['ana_environment_file']+", "
                COMMAND_parts['ana_environment_file']=anaenvfile_to_source
        if COMMAND_parts['generator_config'][:5] == "file:":
                gen_config_parts=COMMAND_parts['generator_config'].split("/")
                gen_config_to_use=gen_config_parts[len(gen_config_parts)-1]
                additional_passins+=COMMAND_parts['generator_config'][5:]+", "
                COMMAND_parts['generator_config']="file:../"+gen_config_to_use #"file:/srv/"+gen_config_to_use
        elif COMMAND_parts['generator_config'] != "NA":
                gen_config_parts=COMMAND_parts['generator_config'].split("/")
                gen_config_to_use=gen_config_parts[len(gen_config_parts)-1]
                additional_passins+=COMMAND_parts['generator_config']+", "
                COMMAND_parts['generator_config']="../"+gen_config_to_use #"/srv/"+gen_config_to_use

        if COMMAND_parts['generator'][:5] == "file:":
                filegen_parts=COMMAND_parts['generator'][5:].split("/")
                #print filegen_parts
                additional_passins+=COMMAND_parts['generator'][5:]+", "
                COMMAND_parts['generator']="file:../"+filegen_parts[len(filegen_parts)-1] #"file:/srv/"+filegen_parts[len(filegen_parts)-1]

        if COMMAND_parts['generator_post_config'] != "Default":
                gen_post_config_parts=COMMAND_parts['generator_post_config'].split("/")
                gen_post_config_to_use=gen_post_config_parts[len(gen_post_config_parts)-1]
                additional_passins+=COMMAND_parts['generator_post_config']+", "
                COMMAND_parts['generator_post_config']="../"+gen_post_config_to_use #"/srv/"+gen_post_config_to_use

        if COMMAND_parts['generator_post_configevt'] != "Default":
                gen_post_configevt_parts=COMMAND_parts['generator_post_configevt'].split("/")
                gen_post_configevt_to_use=gen_post_configevt_parts[len(gen_post_configevt_parts)-1]
                additional_passins+=COMMAND_parts['generator_post_configevt']+", "
                COMMAND_parts['generator_post_configevt']="../"+gen_post_configevt_to_use #"/srv/"+gen_post_configevt_to_use

        if COMMAND_parts['generator_post_configdec'] != "Default":
                gen_post_configdec_parts=COMMAND_parts['generator_post_configdec'].split("/")
                gen_post_configdec_to_use=gen_post_configdec_parts[len(gen_post_configdec_parts)-1]
                additional_passins+=COMMAND_parts['generator_post_configdec']+", "
                COMMAND_parts['generator_post_configdec']="../"+gen_post_configdec_to_use #"/srv/"+gen_post_configdec_to_use

        if (COMMAND_parts['background_to_include'] == "Random" and COMMAND_parts['num_rand_trigs'] == -1 ) or COMMAND_parts['background_to_include'][:4] == "loc:" or ship_random_triggers:
                formattedRUNNUM=""
                for i in range(len(str(RUNNUM)),6):
                        formattedRUNNUM+="0"
                formattedRUNNUM=formattedRUNNUM+str(RUNNUM)
                if COMMAND_parts['background_to_include'] == "Random":
                        #print "/cache/halld/Simulation/random_triggers/"+RANDBGTAG+"/run"+formattedRUNNUM+"_random.hddm"
                        additional_passins+="/osgpool/halld/random_triggers/"+RANDBGTAG+"/run"+formattedRUNNUM+"_random.hddm"+", "
                elif COMMAND_parts['background_to_include'][:4] == "loc:":
                        #print COMMAND_parts[21][4:]
                        additional_passins+=COMMAND_parts['background_to_include'][4:]+"/run"+formattedRUNNUM+"_random.hddm"+", "


        if COMMAND_parts['custom_plugins'] != "None" and COMMAND_parts['custom_plugins'][:5]=="file:" :
                janaconfig_parts=COMMAND_parts['custom_plugins'].split("/")
                janaconfig_to_use=janaconfig_parts[len(janaconfig_parts)-1]
                additional_passins+=COMMAND_parts['custom_plugins'][5:]+", "
                COMMAND_parts['custom_plugins']="file:../"+janaconfig_to_use #"file:/srv/"+janaconfig_to_use

        if COMMAND_parts['custom_ana_plugins'] != "None" and COMMAND_parts['custom_ana_plugins'][:5]=="file:" :
                anajanaconfig_parts=COMMAND_parts['custom_ana_plugins'].split("/")
                anajanaconfig_to_use=anajanaconfig_parts[len(anajanaconfig_parts)-1]
                additional_passins+=COMMAND_parts['custom_ana_plugins'][5:]+", "
                COMMAND_parts['custom_ana_plugins']="file:../"+anajanaconfig_to_use #"file:/srv/"+anajanaconfig_to_use

        if COMMAND_parts['ccdb_sqlite_path'] != "no_sqlite" and COMMAND_parts['ccdb_sqlite_path'] != "batch_default":
                ccdbsqlite_parts=COMMAND_parts['ccdb_sqlite_path'].split("/")
                ccdbsqlite_to_use=ccdbsqlite_parts[len(ccdbsqlite_parts)-1]
                additional_passins+=COMMAND_parts['ccdb_sqlite_path']+", "
                COMMAND_parts['ccdb_sqlite_path']="../"+ccdbsqlite_to_use #"/srv/"+ccdbsqlite_to_use

        if COMMAND_parts['rcdb_sqlite_path'] != "no_sqlite" and COMMAND_parts['rcdb_sqlite_path'] != "batch_default":
                rcdbsqlite_parts=COMMAND_parts['rcdb_sqlite_path'].split("/")
                rcdbsqlite_to_use=rcdbsqlite_parts[len(rcdbsqlite_parts)-1]
                additional_passins+=COMMAND_parts['rcdb_sqlite_path']+", "
                COMMAND_parts['rcdb_sqlite_path']="../"+rcdbsqlite_to_use #"/srv/"+rcdbsqlite_to_use

        if COMMAND_parts['flux_to_generate'] != "unset" and COMMAND_parts['flux_to_generate']!="ccdb" and COMMAND_parts['flux_to_generate']!="cobrems" :
                flux_to_use=COMMAND_parts['flux_to_generate']
                additional_passins+=COMMAND_parts['flux_to_generate']+", "
                COMMAND_parts['flux_to_generate']="../"+flux_to_use #"/srv/"+flux_to_use

        if COMMAND_parts['polarization_to_generate']!="ccdb" and COMMAND_parts['polarization_histogram'] != "unset":
                tpol_to_use=COMMAND_parts['polarization_to_generate']
                additional_passins+=COMMAND_parts['polarization_to_generate']+", "
                COMMAND_parts['polarization_to_generate']="../"+flux_to_use #"/srv/"+tpol_to_use

        if additional_passins != "":
                additional_passins=", "+additional_passins
                additional_passins=additional_passins[:-2]

        f=open('MCOSG_'+str(PROJECT_ID)+'.submit','w')
        f.write("universe = vanilla"+"\n")
        f.write("Executable = "+os.environ.get('MCWRAPPER_CENTRAL')+"/osg-container.sh"+"\n")
        f.write('+ProjectName = "gluex"'+"\n")
        #f.write("Arguments  = "+SCRIPT_TO_RUN+" "+COMMAND+"\n")
        f.write("Arguments  = "+"./"+script_to_use+" "+getCommandString(COMMAND_parts,"OSG",numJobsInBundle)+"\n")
        f.write("Requirements = (HAS_SINGULARITY == TRUE) && (HAS_CVMFS_oasis_opensciencegrid_org == True) && (TARGET.GLIDEIN_Entry_Name =!= \"OSG_US_ODU-Ubuntu\")"+"\n")
        #f.write("Requirements = (HAS_SINGULARITY == TRUE) && (HAS_CVMFS_oasis_opensciencegrid_org == True) && (TARGET.GLIDEIN_Entry_Name =!= \"OSG_US_ODU-Ubuntu\") &&  GLIDEIN_ResourceName==\"ComputeCanada-Cedar\""+"\n")
        #f.write("Requirements = (HAS_SINGULARITY == TRUE) && (HAS_CVMFS_oasis_opensciencegrid_org == True) && (TARGET.GLIDEIN_Entry_Name =!= \"OSG_US_ODU-Ubuntu\") &&  GLIDEIN_ResourceName==\"JLab-FARM-CE\""+"\n")
        #f.write("Requirements = (HAS_SINGULARITY == TRUE) && (HAS_CVMFS_oasis_opensciencegrid_org == True) && (GLIDEIN_SITE=!=\"UConn\") && (GLIDEIN_SITE=!=\"Cedar\")"+"\n")
#        f.write("Requirements = (HAS_SINGULARITY == TRUE) && (HAS_CVMFS_oasis_opensciencegrid_org == True) && (GLIDEIN_SITE==\"UConn\")"+"\n")
        #f.write('wantjobrouter=true'+"\n")
        
        
        if("data_mirror_test" in DATA_OUTPUT_BASE_DIR):
                f.write('+SingularityImage = "/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_devel:latest"'+"\n")
                f.write("use_oauth_services = jlab_gluex"+"\n")
        else:
                f.write('+SingularityImage = "/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_devel:latest"'+"\n")
                #f.write('+SingularityImage = "/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_prod:v1"'+"\n")
                f.write("use_oauth_services = jlab_gluex"+"\n")

        f.write('+SingularityBindCVMFS = True'+"\n")
        #f.write('+UNDESIRED_Sites = "OSG_US_ODU-Ubuntu"'+"\n")
        f.write('+SingularityAutoLoad = True'+"\n")
        
#        f.write('+CVMFSReposList = "oasis.opensciencegrid.org"'+"\n")
        #f.write('+DesiredSites="JLab-FARM-CE"'+"\n")
        
        f.write('should_transfer_files = YES'+"\n")
        #f.write('should_transfer_files = NO'+"\n")
        #f.write('when_to_transfer_output = ON_EXIT'+"\n")

        #f.write('should_transfer_files = NO'+"\n")

        f.write('concurrency_limits = GluexProduction'+"\n")
        f.write('on_exit_remove = true'+"\n")
        f.write('on_exit_hold = false'+"\n")

        #STUBNAME = STUBNAME+str(RUNNUM) + "_" + str(FILENUM)
        #JOBNAME = WORKFLOW + "_" + STUBNAME

        f.write("Error      = "+DATA_OUTPUT_BASE_DIR+"/log/"+"error_"+JOBNAME+".log\n")
        f.write("output      = "+DATA_OUTPUT_BASE_DIR+"/log/"+"out_"+JOBNAME+".log\n")
        f.write("log = "+LOG_DIR+"/log/"+"OSG_"+JOBNAME+".log\n")
        f.write("initialdir = "+RUNNING_DIR+"\n")

        
        f.write("request_cpus = "+str(NCORES)+"\n")
        
        f.write("request_memory = "+str(RAM)+"\n")

        f.write("request_disk = 5.0GB"+"\n")
        #f.write("transfer_input_files = "+ENVFILE+"\n")
        f.write("transfer_input_files = "+SCRIPT_TO_RUN+", "+ENVFILE+additional_passins+"\n")

        #if(numJobsInBundle==1):
        #        f.write("transfer_output_files = "+str(RUNNUM)+"_"+str(FILENUM)+"\n")
        #        f.write("transfer_output_remaps = "+"\""+str(RUNNUM)+"_"+str(FILENUM)+"="+DATA_OUTPUT_BASE_DIR+"\""+"\n")
        #else:
        #        f.write("transfer_output_files = "+str(RUNNUM)+"_$(Process)"+"\n")
        #        f.write("transfer_output_remaps = "+"\""+str(RUNNUM)+"_$(Process)"+"="+DATA_OUTPUT_BASE_DIR+"\""+"\n")

        f.write("queue "+str(numJobsInBundle)+"\n")
        f.close()


        JOBNAME=JOBNAME.replace(".","p")
        #"condor_submit -batch-name "+WORKFLOW+" MCcondor.submit"
        #add_command="condor_submit -name "+JOBNAME+" MCOSG_"+str(PROJECT_ID)+".submit"
        add_command="condor_submit "+"MCOSG_"+str(PROJECT_ID)+".submit"
        if add_command.find(';')!=-1 or add_command.find('&')!=-1 :#THIS CHECK HELPS PROTEXT AGAINST A POTENTIAL HACK VIA CONFIG FILES
                print( "Nice try.....you cannot use ; or &")
                exit(1)


        mkdircom2="mkdir -p "+LOG_DIR+"/log/"
        status2 = subprocess.call(mkdircom2, shell=True)
        status = subprocess.call(mkdircom, shell=True)
        SWIF_ID_NUM="-1"
        if( int(PROJECT_ID) <=0 ):
                
                #do in Popen with the environment
                #print(add_command)
                #add bearer token to env
                os.environ["BEARER_TOKEN_FILE"]="/var/run/user/10967/bt_u10967"
                os.environ["XDG_RUNTIME_DIR"]="/run/user/10967"
                
                token_str='eval `ssh-agent`; /usr/bin/ssh-add;'
                agent_kill_str="; ssh-agent -k"
                print("Submitting: ",token_str+add_command+agent_kill_str)

                

                jobSubout,jobSuberr=subprocess.Popen(token_str+add_command+agent_kill_str,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=os.environ,executable='/bin/bash',close_fds=True).communicate()
                #jobSubout=subprocess.check_output(add_command.split(" "))
                print("JOBSUB OUTPUT",jobSubout)
                print("JOBSUB ERROR",jobSuberr)
                #'Agent pid 2322136\nSubmitting job(s).\n1 job(s) submitted to cluster 925999.\n'
                idnumline=jobSubout.split("\n")[2].split(".")[0].split(" ")
                

                #1 job(s) submitted to cluster 425013.


                status = subprocess.call('rm -f MCOSG_'+str(PROJECT_ID)+'.submit', shell=True)
                status = subprocess.call('rm -f /tmp/MCOSG_'+str(PROJECT_ID)+'.submit', shell=True)

                #print "DECIDING IF FIRST JOB"
                #print PROJECT_ID

        if int(PROJECT_ID) > 0:
                #print "FIRST ATTEMPT"
                recordJob(PROJECT_ID,RUNNUM,FILENUM,SWIF_ID_NUM,COMMAND['num_events'])
                #recordFirstAttempt(PROJECT_ID,RUNNUM,FILENUM,"OSG",SWIF_ID_NUM,COMMAND['num_events'],NCORES,"Unset")
        elif int(PROJECT_ID) < 0:
                if(int(idnumline[0])==numJobsInBundle):
                        #print "A NEW SET OF ATTEMPTS"
                        #print("JOBS BUNDLE:",bundledJobs)
                        transactions_Array=[]
                        trans_block_count=0
                        transaction_stub="INSERT INTO Attempts (Job_ID,Creation_Time,BatchSystem,SubmitHost,BatchJobID,Status,WallTime,CPUTime,ThreadsRequested,RAMRequested, RAMUsed) VALUES "
                        transaction_str=""
                        #print("BUNDLING!")
                        for job in bundledJobs:
                                #***********************
                                #THE FOLLOWING IF CHECKS IF THE ASSIGNED BATCH ID HAS BEEN ASSIGNED BEFORE FROM SCOSG16
                                #THIS OCCURED BEFORE CAUSING UNIQUENESS TO BE VIOLATED AND REQUIRING ~8K JOBS TO BE SCRUBBED
                                #***********************
                                if(trans_block_count % 500 == 0 and trans_block_count != 0):
                                        transactions_Array.append(transaction_stub+transaction_str[:-2])
                                        transaction_str=""

                               #print("JOB:",job)
                                SWIF_ID_NUM=str(idnumline[5])+".0"
                                if(numJobsInBundle>1):
                                        SWIF_ID_NUM=str(idnumline[5])+"."+str(job[1])

                                #if int(PROJECT_ID) !=0:
                                #        findmyjob="SELECT * FROM Attempts where BatchJobID='"+str(SWIF_ID_NUM)+"' && BatchSystem='OSG';"
                                #        dbcursor.execute(findmyjob)
                                #        MYJOB = dbcursor.fetchall()

                                #if len(MYJOB) != 0:
                                #        #SELECT DISTINCT Project_ID FROM Jobs where ID in (select Job_ID from Attempts WHERE BatchSystem='OSG' GROUP BY BatchJobID HAVING COUNT(Job_ID)>1 ORDER BY BatchJobID DESC);
                                #        print("THE TIMELINE HAS BEEN FRACTURED. TERMINATING SUBMITS AND SHUTTING THE ROBOT DOWN!!!")
                                #        f=open("/osgpool/halld/tbritton/.ALLSTOP","x")
                                #        exit(1)

                                transaction_str+=Build_recordAttemptString(int(job[0]),RUNNUM,job[1],"OSG","'"+socket.gethostname()+"'",SWIF_ID_NUM,COMMAND['num_events'],NCORES,"Unset")+", "
                                trans_block_count+=1
                                #print(transaction_str)
                                #recordAttempt(int(job[0]),RUNNUM,job[1],"OSG",SWIF_ID_NUM,COMMAND['num_events'],NCORES,"Unset")

                        if(transaction_str != ""):
                                transactions_Array.append(transaction_stub+transaction_str[:-2])

                        #print(transactions_Array)
                        for transaction in transactions_Array:
                                print(transaction)
                                print("===================================================")
                                Transact_recordAttempt(transaction)

#====================================================
#Takes in a few pertinant pieces of info.  Submits to the JSUB
#Currently a stub. No time to implement (or real demand)
#====================================================
def JSUB_add_job(VERBOSE, WORKFLOW, PROJECT,TRACK, RUNNUM, FILENUM, SCRIPT_TO_RUN, COMMAND, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID):
        STUBNAME=""
        if(COMMAND['custom_tag_string'] != "I_dont_have_one"):
                STUBNAME=COMMAND['custom_tag_string']+"_"
        # PREPARE NAMES
        STUBNAME = STUBNAME+str(RUNNUM) + "_" + str(FILENUM)
        JOBNAME = WORKFLOW + "_" + STUBNAME

        #mkdircom="mkdir -p "+DATA_OUTPUT_BASE_DIR+"/log/"

        f=open('MCJSUB.submit','w')
        f.write("<Request>"+"\n")

        f.write("<Project name=\""+PROJECT+"\"/>"+"\n")
        f.write("<Track name=\""+TRACK+"\"/>"+"\n")
        f.write("<Name name=\""+JOBNAME+"\"/>"+"\n")
        f.write("<Command><![CDATA[ "+SCRIPT_TO_RUN+" "+getCommandString(COMMAND,"JSUB")+" ]></Command>"+"\n")
        f.write("<Job> </Job>"+"\n")
        f.write("</Request>"+"\n")

        f.close()

        exit(1)
#====================================================
#Takes in a few pertinant pieces of info.  Submits to SLURM
#This was originally targetting NERSC.  Then JLab announced a switch to slurm.  And then swif did it.  If there is demand this should be finished up
#if project ID is less than 0 its an attempt ID and is recorded as such
#if project ID is greater than 0 then it is a project ID and this call is going to record a new job (NOT ACTUALLY MAKING THE ATTEMPT)
#if project ID == 0 then it is neither and just scrape the batch_ID....do nothing.  Note: this scheme requires the first id in the tables to be 1 and not 0)
#====================================================
def  SLURMcont_add_job(VERBOSE, WORKFLOW, RUNNUM, FILENUM, SCRIPT_TO_RUN, COMMAND, NCORES, RAM, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID ):
        STUBNAME=""
        if(COMMAND['custom_tag_string'] != "I_dont_have_one"):
                STUBNAME=COMMAND['custom_tag_string']+"_"
        # PREPARE NAMES
        STUBNAME = STUBNAME+str(RUNNUM) + "_" + str(FILENUM)
        JOBNAME = WORKFLOW + "_" + STUBNAME

        mkdircom="mkdir -p "+DATA_OUTPUT_BASE_DIR+"/log/"
        status = subprocess.call(mkdircom, shell=True)

        f=open('MCSLURM.submit','w')
        f.write("#!/bin/bash -l"+"\n")
        f.write("#SBATCH -J "+JOBNAME+"\n")
        #f.write("#SBATCH --image=/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_prod:v1"+"\n")
        f.write("#SBATCH --nodes=1"+"\n")
        f.write("#SBATCH --time="+TIMELIMIT+"\n")
        f.write("#SBATCH --tasks-per-node=1"+"\n")
        f.write("#SBATCH --cpus-per-task="+NCORES+"\n")
        f.write("#SBATCH --mem="+RAM+"\n")

        #f.write("#SBATCH -A gluex"+"\n")
        f.write("#SBATCH -p production"+"\n")
        f.write("#SBATCH -o "+DATA_OUTPUT_BASE_DIR+"/log/"+JOBNAME+".out\n")
        f.write("#SBATCH -e "+DATA_OUTPUT_BASE_DIR+"/log/"+JOBNAME+".err\n")

        #f.write("srun "+SCRIPT_TO_RUN+" "+COMMAND+"\n")
        #/group/halld/www/halldweb/html/dist/gluex_centos7.img /cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_prod:v1
        f.write("singularity exec --bind /scigroup/mcwrapper/ --bind /u --bind /group/halld/ --bind /scratch/slurm/ --bind /cvmfs --bind /work/osgpool/ --bind /work/halld --bind /cache/halld --bind /volatile/halld --bind /work/halld2 /cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_prod:v1 $MCWRAPPER_CENTRAL/MakeMC.sh "+getCommandString(COMMAND,"SBATCH_SLURM")+"\n")
        #print(getCommandString(COMMAND,"SBATCH_SLURM"))
        f.close()

        if( int(PROJECT_ID) <=0 ):
                add_command="sbatch MCSLURM.submit"
                if add_command.find(';')!=-1 or add_command.find('&')!=-1 :#THIS CHECK HELPS PROTEXT AGAINST A POTENTIAL HACK VIA CONFIG FILES
                        print( "Nice try.....you cannot use ; or &")
                        exit(1)

        if int(PROJECT_ID) > 0:
                recordJob(PROJECT_ID,RUNNO,FILENO,SWIF_ID_NUM,COMMAND['num_events'])
                #recordFirstAttempt(PROJECT_ID,RUNNO,FILENO,"SLURM",SWIF_ID_NUM,COMMAND['num_events'],NCORES, "UnSet")
        elif int(PROJECT_ID) < 0:
                recordAttempt(abs(int(PROJECT_ID)),RUNNO,FILENO,"SLURM",SWIF_ID_NUM,COMMAND['num_events'],NCORES,"UnSet")


        status = subprocess.call(add_command, shell=True)
        status = subprocess.call("rm MCSLURM.submit", shell=True)

def  SLURM_add_job(VERBOSE, WORKFLOW, RUNNUM, FILENUM, SCRIPT_TO_RUN, COMMAND, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID ):
        STUBNAME=""
        if(COMMAND['custom_tag_string'] != "I_dont_have_one"):
                STUBNAME=COMMAND['custom_tag_string']+"_"
        # PREPARE NAMES
        STUBNAME = STUBNAME+str(RUNNUM) + "_" + str(FILENUM)
        JOBNAME = WORKFLOW + "_" + STUBNAME

        mkdircom="mkdir -p "+DATA_OUTPUT_BASE_DIR+"/log/"
        status = subprocess.call(mkdircom, shell=True)

        f=open('MCSLURM.submit','w')
        f.write("#!/bin/bash -l"+"\n")
        f.write("#SBATCH -J "+JOBNAME+"\n")
        #f.write("#SBATCH --image=/cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_prod:v1"+"\n")
        f.write("#SBATCH --nodes=1"+"\n")
        f.write("#SBATCH --time="+TIMELIMIT+"\n")
        f.write("#SBATCH --tasks-per-node=1"+"\n")
        f.write("#SBATCH --cpus-per-task="+NCORES+"\n")

        #f.write("#SBATCH -A gluex"+"\n")
        f.write("#SBATCH -p production"+"\n")
        f.write("#SBATCH -o "+DATA_OUTPUT_BASE_DIR+"/log/"+JOBNAME+".out\n")
        f.write("#SBATCH -e "+DATA_OUTPUT_BASE_DIR+"/log/"+JOBNAME+".err\n")

        #f.write("srun "+SCRIPT_TO_RUN+" "+COMMAND+"\n")
        #/group/halld/www/halldweb/html/dist/gluex_centos7.img /cvmfs/singularity.opensciencegrid.org/jeffersonlab/gluex_prod:v1
        f.write(SCRIPT_TO_RUN+" "+getCommandString(COMMAND,"SLURM")+"\n")

        f.close()

        if( int(PROJECT_ID) <=0 ):
                add_command="sbatch MCSLURM.submit"
                if add_command.find(';')!=-1 or add_command.find('&')!=-1 :#THIS CHECK HELPS PROTEXT AGAINST A POTENTIAL HACK VIA CONFIG FILES
                        print( "Nice try.....you cannot use ; or &")
                        exit(1)

        if int(PROJECT_ID) > 0:
                recordJob(PROJECT_ID,RUNNO,FILENO,SWIF_ID_NUM,COMMAND['num_events'])
                #recordFirstAttempt(PROJECT_ID,RUNNO,FILENO,"SLURM",SWIF_ID_NUM,COMMAND['num_events'],NCORES, "UnSet")
        elif int(PROJECT_ID) < 0:
                recordAttempt(abs(int(PROJECT_ID)),RUNNO,FILENO,"SLURM",SWIF_ID_NUM,COMMAND['num_events'],NCORES,"UnSet")


        status = subprocess.call(add_command, shell=True)
        status = subprocess.call("rm MCSLURM.submit", shell=True)
#====================================================
#function to split monolithic hddm file by run number
#credit to sdobbs for the base
#====================================================
def split_file_on_run_number(infname):
        # output files
        fout = {}
        outevts = {}
        # iterate through the file, splitting by run number
        for rec in hddm_r.istream(infnamepath):
                evt = rec.getReconstructedPhysicsEvent()
                if evt.runNo not in fout:
                        outfname = "{0}_run{1}.hddm".format(infname[:-5],evt.runNo)
                        print("Creating output file {0} ...".format(outfname))
                        fout[evt.runNo] = hddm_r.ostream(outfname)
                        outevts[evt.runNo] = 0
                else:
                        outevts[evt.runNo] += 1
                fout[evt.runNo].write(rec)

        print(fout)
        print(outevts)
        return outevts

#====================================================
#Simple function to take in the column information and insert into the Jobs Table
#====================================================
def recordJob(PROJECT_ID,RUNNO,FILENO,BatchJobID, NUMEVTS):
        dbcursor.execute("INSERT INTO Jobs (Project_ID, RunNumber, FileNumber, Creation_Time, IsActive, NumEvts) VALUES ("+str(PROJECT_ID)+", "+str(RUNNO)+", "+str(FILENO)+", NOW(), 1, "+str(NUMEVTS)+")")
        dbcnx.commit()
#====================================================
#This deprecated function used to find the job to attach to and indsert into the jobs table
#====================================================
def recordFirstAttempt(PROJECT_ID,RUNNO,FILENO,BatchSYS,BatchJobID, NUMEVTS,NCORES, RAM):
        findmyjob="SELECT ID FROM Jobs WHERE Project_ID="+str(PROJECT_ID)+" && RunNumber="+str(RUNNO)+" && FileNumber="+str(FILENO)+" && NumEvts="+str(NUMEVTS)+" && IsActive=1;"
        dbcursor.execute(findmyjob)
        MYJOB = dbcursor.fetchall()

        if len(MYJOB) != 1:
                print("I either can't find a job or too many jobs might be mine")
                exit(1)

        Job_ID=MYJOB[0][0]

        addAttempt="INSERT INTO Attempts (Job_ID,Creation_Time,BatchSystem,HostName,BatchJobID,Status,WallTime,CPUTime,ThreadsRequested,RAMRequested, RAMUsed) VALUES ("+str(Job_ID)+", NOW(), "+str("'"+BatchSYS+"'")+", "+str(socket.gethostname())+", "+str(BatchJobID)+", 'Created', 0, 0, "+str(NCORES)+", "+str("'"+RAM+"'")+", '0'"+");"

        print(addAttempt)
        dbcursor.execute(addAttempt)
        dbcnx.commit()
#====================================================
#This function attaches itself directly to the passed in JOB_ID and inserts a new job
#====================================================
def Transact_recordAttempt(trans_string):
        #print(trans_string)
        dbcursor.execute(trans_string)#,multi=True)
        dbcnx.commit()

def Build_recordAttemptString(JOB_ID,RUNNO,FILENO,BatchSYS,hostname,BatchJobID, NUMEVTS,NCORES, RAM):
        #findmyjob="SELECT * FROM Jobs WHERE ID="+str(JOB_ID)
        ##print findmyjob
        #dbcursor.execute(findmyjob)
        #MYJOB = dbcursor.fetchall()

        #print MYJOB#

        #if len(MYJOB) != 1:
        #        print("I either can't find a job or too many jobs might be mine")
        #        exit(1)

        #Job_ID=MYJOB[0][0]

        addAttempt="("+str(JOB_ID)+", NOW(), "+str("'"+BatchSYS+"'")+", "+str(hostname)+", "+str(BatchJobID)+", 'Created', 0, 0, "+str(NCORES)+", "+str("'"+RAM+"'")+", '0'"+")"
        return addAttempt

def recordAttempt(JOB_ID,RUNNO,FILENO,BatchSYS,BatchJobID, NUMEVTS,NCORES, RAM):
        #print "RECORDING ATTEMPT"
        #print JOB_ID
        findmyjob="SELECT * FROM Jobs WHERE ID="+str(JOB_ID)
        #print findmyjob
        dbcursor.execute(findmyjob)
        MYJOB = dbcursor.fetchall()

        #print MYJOB

        if len(MYJOB) != 1:
                print("I either can't find a job or too many jobs might be mine")
                exit(1)

        Job_ID=MYJOB[0][0]

        addAttempt="INSERT INTO Attempts (Job_ID,Creation_Time,BatchSystem,SubmitHost,BatchJobID,Status,WallTime,CPUTime,ThreadsRequested,RAMRequested, RAMUsed) VALUES ("+str(JOB_ID)+", NOW(), "+str("'"+BatchSYS+"'")+", "+str(socket.gethostname())+", "+str(BatchJobID)+", 'Created', 0, 0, "+str(NCORES)+", "+str("'"+RAM+"'")+", '0'"+");"
        print(addAttempt)
        dbcursor.execute(addAttempt)
        dbcnx.commit()

#====================================================
#The argument string passed to the MakeMC script is order dependent.  THe following is that order.
#it is dictionary based and should be fairly trivial to redesign into an order independent method
#if a new MakeMC script came around this is where you would add an if and conform to its requirements
#the COMMAND dictionary expects ALL the KEYS
#====================================================
def getCommandString(COMMAND,USER,numbundled=1):
        if(USER=="OSG" and numbundled!=1):
                return COMMAND['batchrun']+" "+COMMAND['environment_file']+" "+COMMAND['ana_environment_file']+" "+COMMAND['generator_config']+" "+COMMAND['output_directory']+" "+COMMAND['run_number']+" "+"$(Process)"+" "+COMMAND['num_events']+" "+COMMAND['jana_calib_context']+" "+COMMAND['jana_calibtime']+" "+COMMAND['do_gen']+" "+COMMAND['do_geant']+" "+COMMAND['do_mcsmear']+" "+COMMAND['do_recon']+" "+COMMAND['clean_gen']+" "+COMMAND['clean_geant']+" "+COMMAND['clean_mcsmear']+" "+COMMAND['clean_recon']+" "+COMMAND['batch_system']+" "+COMMAND['num_cores']+" "+COMMAND['generator']+" "+COMMAND['geant_version']+" "+COMMAND['background_to_include']+" "+COMMAND['custom_Gcontrol']+" "+COMMAND['eBeam_energy']+" "+COMMAND['coherent_peak']+" "+COMMAND['min_generator_energy']+" "+COMMAND['max_generator_energy']+" "+COMMAND['upper_vertex_indices']+" "+COMMAND['lower_vertex_indices']+" "+COMMAND['custom_tag_string']+" "+COMMAND['custom_plugins']+" "+COMMAND['custom_ana_plugins']+" "+COMMAND['events_per_file']+" "+COMMAND['running_directory']+" "+COMMAND['ccdb_sqlite_path']+" "+COMMAND['rcdb_sqlite_path']+" "+COMMAND['background_tagger_only']+" "+COMMAND['radiator_thickness']+" "+COMMAND['background_rate']+" "+COMMAND['random_background_tag']+" "+COMMAND['recon_calibtime']+" "+COMMAND['no_geant_secondaries']+" "+COMMAND['mcwrapper_version']+" "+COMMAND['no_bcal_sipm_saturation']+" "+COMMAND['flux_to_generate']+" "+COMMAND['flux_histogram']+" "+COMMAND['polarization_to_generate']+" "+COMMAND['polarization_histogram']+" "+COMMAND['eBeam_current']+" "+COMMAND['experiment']+" "+COMMAND['num_rand_trigs']+" "+COMMAND['location']+" "+COMMAND['generator_post']+" "+COMMAND['generator_post_config']+" "+COMMAND['generator_post_configevt']+" "+COMMAND['generator_post_configdec']+" "+COMMAND['geant_vertex_area']+" "+COMMAND['geant_vertex_length']+" "+COMMAND['mcsmear_notag']+" "+COMMAND['project_directory_name']
        else:
                return COMMAND['batchrun']+" "+COMMAND['environment_file']+" "+COMMAND['ana_environment_file']+" "+COMMAND['generator_config']+" "+COMMAND['output_directory']+" "+COMMAND['run_number']+" "+COMMAND['file_number']+" "+COMMAND['num_events']+" "+COMMAND['jana_calib_context']+" "+COMMAND['jana_calibtime']+" "+COMMAND['do_gen']+" "+COMMAND['do_geant']+" "+COMMAND['do_mcsmear']+" "+COMMAND['do_recon']+" "+COMMAND['clean_gen']+" "+COMMAND['clean_geant']+" "+COMMAND['clean_mcsmear']+" "+COMMAND['clean_recon']+" "+COMMAND['batch_system']+" "+COMMAND['num_cores']+" "+COMMAND['generator']+" "+COMMAND['geant_version']+" "+COMMAND['background_to_include']+" "+COMMAND['custom_Gcontrol']+" "+COMMAND['eBeam_energy']+" "+COMMAND['coherent_peak']+" "+COMMAND['min_generator_energy']+" "+COMMAND['max_generator_energy']+" "+COMMAND['upper_vertex_indices']+" "+COMMAND['lower_vertex_indices']+" "+COMMAND['custom_tag_string']+" "+COMMAND['custom_plugins']+" "+COMMAND['custom_ana_plugins']+" "+COMMAND['events_per_file']+" "+COMMAND['running_directory']+" "+COMMAND['ccdb_sqlite_path']+" "+COMMAND['rcdb_sqlite_path']+" "+COMMAND['background_tagger_only']+" "+COMMAND['radiator_thickness']+" "+COMMAND['background_rate']+" "+COMMAND['random_background_tag']+" "+COMMAND['recon_calibtime']+" "+COMMAND['no_geant_secondaries']+" "+COMMAND['mcwrapper_version']+" "+COMMAND['no_bcal_sipm_saturation']+" "+COMMAND['flux_to_generate']+" "+COMMAND['flux_histogram']+" "+COMMAND['polarization_to_generate']+" "+COMMAND['polarization_histogram']+" "+COMMAND['eBeam_current']+" "+COMMAND['experiment']+" "+COMMAND['num_rand_trigs']+" "+COMMAND['location']+" "+COMMAND['generator_post']+" "+COMMAND['generator_post_config']+" "+COMMAND['generator_post_configevt']+" "+COMMAND['generator_post_configdec']+" "+COMMAND['geant_vertex_area']+" "+COMMAND['geant_vertex_length']+" "+COMMAND['mcsmear_notag']+" "+COMMAND['project_directory_name']
def LoadCCDB():
        sqlite_connect_str = "mysql://ccdb_user@hallddb.jlab.org/ccdb"
        provider = ccdb.AlchemyProvider()                           # this class has all CCDB manipulation functions
        provider.connect(sqlite_connect_str)                        # use usual connection string to connect to database
        provider.authentication.current_user_name = "psflux_user"   # to have a name in logs

        return provider

def PSAcceptance(x, par0, par1, par2):
    min = par1
    max = par2

    if x > 2.*min and x < min + max:
        return par0*(1-2.*min/x)
    elif x >= min + max:
        return par0*(2.*max/x - 1)

    return 0.


def calcFluxCCDB(ccdb_conn, run, emin, emax):

        flux = 0.
        VARIATION = "default"
        CALIBTIME = datetime.now()
        CALIBTIME_USER = CALIBTIME
        CALIBTIME_ENERGY = CALIBTIME

        # Set livetime scale factor
        livetime_ratio = 0.0
        try:
                livetime_assignment = ccdb_conn.get_assignment("/PHOTON_BEAM/pair_spectrometer/lumi/trig_live", run[0], VARIATION, CALIBTIME)
                livetime = livetime_assignment.constant_set.data_table
                if float(livetime[3][1]) > 0.0: # check that livetimes are non-zero
                       livetime_ratio = float(livetime[0][1])/float(livetime[3][1])
                else: # if bad livetime assume ratio is 1
                       livetime_ratio = 1.0
        except:
                livetime_ratio = 1.0 # default to unity if table doesn't exist

        # Conversion factors for total flux
        converterThickness = run[2]
        converterLength = 75e-6 # default is 75 um
        if converterThickness == "Be 750um":
                converterLength = 750e-6
        elif converterThickness != "Be 75um":
                print("Unknown converter thickness for run %s: %s, assuming Be 75um" % (run[0],run[2]))

        berilliumRL = 35.28e-2 # 35.28 cm
        radiationLength = converterLength/berilliumRL
        scale = livetime_ratio * 1./((7/9.) * radiationLength)

        photon_endpoint = array('d')
        tagh_untagged_flux = array('d')
        tagh_scaled_energy = array('d')

        try:
                photon_endpoint_assignment = ccdb_conn.get_assignment("/PHOTON_BEAM/endpoint_energy", run[0], VARIATION, CALIBTIME_ENERGY)
                photon_endpoint = photon_endpoint_assignment.constant_set.data_table

                tagh_untagged_flux_assignment = ccdb_conn.get_assignment("/PHOTON_BEAM/pair_spectrometer/lumi/tagh/untagged", run[0], VARIATION, CALIBTIME)
                tagh_untagged_flux = tagh_untagged_flux_assignment.constant_set.data_table
                tagh_scaled_energy_assignment = ccdb_conn.get_assignment("/PHOTON_BEAM/hodoscope/scaled_energy_range", run[0], VARIATION, CALIBTIME_ENERGY)
                tagh_scaled_energy_table = tagh_scaled_energy_assignment.constant_set.data_table
                PS_accept_assignment = ccdb_conn.get_assignment("/PHOTON_BEAM/pair_spectrometer/lumi/PS_accept", run[0], VARIATION, CALIBTIME)
                PS_accept = PS_accept_assignment.constant_set.data_table
        except:
                print("Missing flux for run number = %d, skipping generation" % run[0])
                return -1.0

        # sum untagged flux
        for tagh_flux, tagh_scaled_energy in zip(tagh_untagged_flux, tagh_scaled_energy_table):
                tagh_energy = float(photon_endpoint[0][0])*(float(tagh_scaled_energy[1])+float(tagh_scaled_energy[2]))/2.

                if tagh_energy < emin or tagh_energy > emax:
                        continue

                psAccept = PSAcceptance(tagh_energy, float(PS_accept[0][0]), float(PS_accept[0][1]), float(PS_accept[0][2]))
                if psAccept <= 0.0:
                        continue

                flux = flux + float(tagh_flux[1]) * scale / psAccept

        return flux

def showhelp():
        helpstring= "variation=%s where %s is a valid jana_calib_context variation string (default is \"mc\")\n"
        helpstring+= " per_file=%i where %i is the number of events you want per file/job (default is 10000)\n"
        helpstring+= " base_file_number=%i where %i is the starting number of the files/jobs (default is 0)\n"
        helpstring+= " numthreads=%i sets the number of threads to use to %i.  Note that this will overwrite the NCORES set in MC.config\n"
        helpstring+= " generate=[0/1] where 0 means that the generation step and any subsequent step will not run (default is 1)\n"
        helpstring+= " geant=[0/1] where 0 means that the geant step and any subsequent step will not run (default is 1)\n"
        helpstring+= " mcsmear=[0/1] where 0 means that the mcsmear step and any subsequent step will not run (default is 1)\n"
        helpstring+= " recon=[0/1] where 0 means that the reconstruction step will not run (default is 1)\n"
        helpstring+= " cleangenerate=[0/1] where 0 means that the generation step will not be cleaned up after use (default is 1)\n"
        helpstring+= " cleangeant=[0/1] where 0 means that the geant step will not be cleaned up after use (default is 1)\n"
        helpstring+= " cleanmcsmear=[0/1] where 0 means that the mcsmear step will not be cleaned up after use (default is 1)\n"
        helpstring+= " cleanrecon=[0/1]where 0 means that the reconstruction step will not be cleaned up after running (default is 0)\n"
        helpstring+= " batch=[0/1/2] where 1 means that jobs will be submitted, 2 will do the same as 1 but also run the workflow in the case of swif(2) (default is 0 [interactive])\n"
        helpstring+= " logdir=[path] will direct the .out and .err files to the specified path for qsub\n"
        return helpstring

########################################################## MAIN ##########################################################

def main(argv):
        parser_usage = "gluex_MC.py config_file Run_Number/Range num_events [all other options]\n\n where [all other options] are:\n\n "
        parser_usage += showhelp()
        parser = OptionParser(usage = parser_usage)
        (options, args) = parser.parse_args(argv)

        #check if there are enough arguments
        if(len(argv)<3):
                parser.print_help()
                return

        #check if the needed arguments are valid
        if len(args[1].split("="))>1 or len(args[2].split("="))>1:
                parser.print_help()
                return

        #!!!!!!!!!!!!!!!!!!REQUIRED COMMAND LINE ARGUMENTS!!!!!!!!!!!!!!!!!!!!!!!!
        CONFIG_FILE = args[0]
        RUNNUM = str(args[1]).lstrip("0")
        EVTS = int(args[2])
        #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

        #BANNER
        print( "*********************************")
        print( "Welcome to v"+str(MCWRAPPER_VERSION)+" of MCwrapper")
        print( "Thomas Britton "+str(MCWRAPPER_DATE))
        print( "*********************************")

        #load all argument passed in and set default options
        VERBOSE    = False

        TAGSTR="I_dont_have_one"

        DATA_OUTPUT_BASE_DIR    = "UNKNOWN_LOCATION"#your desired output location
        RCDB_QUERY=""

        ENVFILE = "my-environment-file" #change this to your own environment file
        ANAENVFILE = "no_Analysis_env"

        GENERATOR = "genr8"
        GENCONFIG = "NA"

        GENPOST="No"
        GENPOSTCONFIG="Default"
        GENPOSTCONFIGEVT="Default"
        GENPOSTCONFIGDEC="Default"

        eBEAM_ENERGY="rcdb"
        eBEAM_CURRENT="rcdb"
        COHERENT_PEAK="rcdb"
        FLUX_TO_GEN="ccdb"
        FLUX_HIST="unset"
        POL_TO_GEN="0.4"
        POL_HIST="unset"
        MIN_GEN_ENERGY="3"
        MAX_GEN_ENERGY="12"
        UPPER_VERTEX_INDICES="unset"
        LOWER_VERTEX_INDICES="unset"

        RADIATOR_THICKNESS="rcdb"
        BGRATE="rcdb" #GHz
        BGTAGONLY="0"
        RUNNING_DIR="./"
        ccdbSQLITEPATH="no_sqlite"
        rcdbSQLITEPATH="no_sqlite"

        GEANTVER = 4
        VERTEX_AREA="ccdb"
        VERTEX_LENGTH="29.5"
        BGFOLD="DEFAULT"
        RANDOM_NUM_EVT=-1
        RANDBGTAG="none"
        SMEAR_NOTAG="0"

        CUSTOM_MAKEMC="DEFAULT"
        CUSTOM_GCONTROL="0"
        CUSTOM_PLUGINS="None"
        CUSTOM_ANA_PLUGINS="None"

        BATCHSYS="NULL"
        QUEUENAME="DEF"
        #-------SWIF ONLY-------------
        # PROJECT INFO
        PROJECT    = "gluex"          # http://scicomp.jlab.org/scicomp/#/projects
        TRACK      = "simulation"     # https://scicomp.jlab.org/docs/batch_job_tracks
        ACCOUNT    = "halld"          # https://scicomp.jlab.org/scicomp/slurmJob/slurmAccount
        PARTITION  = "production"          # https://scicomp.jlab.org/scicomp/slurmJob/slurmInfo
        EXPERIMENT = "GlueX"          # GlueX or CPP
        CONDOR_MAGIC = []
        # RESOURCES for swif jobs
        NCORES     = "8"               # Number of CPU cores
        DISK       = "10GB"            # Max Disk usage
        RAM        = "20GB"            # Max RAM usage
        TIMELIMIT  = "300minutes"      # Max walltime
        OS         = "centos77"        # Specify CentOS65 machines

        PROJECT_ID=0 #internally used when needed
        IS_SUBMITTER=0
        TO_BUNDLE=False
        #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        VERSION  = "mc"
        CALIBTIME="notime"
        RECON_CALIBTIME="notime"
        BASEFILENUM=0
        PERFILE=10000
        GENR=1
        GEANT=1
        SMEAR=1
        RECON=1
        CLEANGENR=1
        CLEANGEANT=1
        CLEANSMEAR=1
        CLEANRECON=0
        BATCHRUN=0
        NOSECONDARIES=0
        NOSIPMSATURATION=0
        SHELL_TO_USE="csh"
        MYJOB=[]
        LOCATION="auto"

        #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
        #loop over config file and set the "parameters"
        #The following could be replaced with a better built in parser
        #At least switch to a switch if you have time!
        f = open(CONFIG_FILE,"r")

        for line in f:
                if len(line)==0:
                       continue
                if line[0]=="#":
                       continue

                parts=line.split("#")[0].split("=",1)
                #print parts
                if len(parts)==1:
                        #print "Warning! No Sets given"
                        continue

                if len(parts)>2 and str(parts[0]).upper() != "VARIATION" and str(parts[0]).upper() != "RCDB_QUERY":
                        print( "warning! I am going to have a really difficult time with:")
                        print( line)
                        print( "I'm going to just ignore it and hope it isn't a problem....")
                        continue


                rm_comments=[]
                if len(parts)>1:
                        rm_comments=parts[len(parts)-1].split("#")

                j=-1
                for i in parts:
                        j=j+1
                        i=i.strip()
                        parts[j]=i

                if str(parts[0]).upper()=="VERBOSE" :
                        if rm_comments[0].strip().upper()=="TRUE" or rm_comments[0].strip() == "1":
                                VERBOSE=True
                elif str(parts[0]).upper()=="PROJECT" :
                        PROJECT=rm_comments[0].strip()
                elif str(parts[0]).upper()=="ACCOUNT" :
                        ACCOUNT=rm_comments[0].strip()
                elif str(parts[0]).upper()=="CONDOR_MAGIC" :
                        #print("detected magic")
                        CONDOR_MAGIC.append(rm_comments[0].strip())
                elif str(parts[0]).upper()=="TRACK" :
                        TRACK=rm_comments[0].strip()
                elif str(parts[0]).upper()=="PARTITION" :
                        PARTITION=rm_comments[0].strip()
                elif str(parts[0]).upper()=="EXPERIMENT" :
                        EXPERIMENT=rm_comments[0].strip()
                elif str(parts[0]).upper()=="NCORES" :
                        NCORES=rm_comments[0].strip()
                elif str(parts[0]).upper()=="DISK" :
                        DISK=rm_comments[0].strip()
                elif str(parts[0]).upper()=="RAM" :
                        RAM=rm_comments[0].strip()
                elif str(parts[0]).upper()=="TIMELIMIT" :
                        TIMELIMIT=rm_comments[0].strip()
                elif str(parts[0]).upper()=="OS" :
                        OS=rm_comments[0].strip()
                elif str(parts[0]).upper()=="DATA_OUTPUT_BASE_DIR" :
                        DATA_OUTPUT_BASE_DIR=rm_comments[0].strip()
                elif str(parts[0]).upper()=="ENVIRONMENT_FILE" :
                        ENVFILE=rm_comments[0].strip()
                elif str(parts[0]).upper()=="ANA_ENVIRONMENT_FILE" :
                        ANAENVFILE=rm_comments[0].strip()
                elif str(parts[0]).upper()=="GENERATOR" :
                        GENERATOR=rm_comments[0].strip()
                elif str(parts[0]).upper()=="GEANT_VERSION" :
                        GEANTVER=rm_comments[0].strip()
                elif str(parts[0]).upper()=="VERTEX_VOLUME" :
                        WHOLEVERT=rm_comments[0].strip()
                        WHOLEVERT_split=WHOLEVERT.split(":")

                        if (len(WHOLEVERT_split)==1):
                                VERTEX_LENGTH=WHOLEVERT_split[0]
                        elif (len(WHOLEVERT_split)==2):
                                VERTEX_AREA=WHOLEVERT_split[0]
                                VERTEX_LENGTH=WHOLEVERT_split[1]

                elif str(parts[0]).upper()=="WORKFLOW_NAME" :
                        WORKFLOW=rm_comments[0].strip()
                        if WORKFLOW.find(';')!=-1 or WORKFLOW.find('&')!=-1 :#THIS CHECK HELPS PROTECT AGAINST A POTENTIAL HACK IN WORKFLOW NAMES
                                print( "Nice try.....you cannot use ; or & in the name")
                                exit(1)
                elif str(parts[0]).upper()=="GENERATOR_CONFIG" :
                        GENCONFIG=rm_comments[0].strip()
                        if len(GENCONFIG.split(" ")) != 1:
                                print(GENCONFIG,"is an invalid GENERATOR_CONFIG parameter. Please fix in",CONFIG_FILE,"exiting...")
                                exit(1)
                elif str(parts[0]).upper()=="GENERATOR_POSTPROCESS":
                        WHOLEPOST=rm_comments[0].strip()
                        WHOLEPOST_PARTS=WHOLEPOST.split(":")
                        GENPOST=WHOLEPOST_PARTS[0]

                        if(len(WHOLEPOST_PARTS)==2):
                                GENPOSTCONFIG="Default" if WHOLEPOST_PARTS[1].lower()=="default" else WHOLEPOST_PARTS[1]
                        elif(len(WHOLEPOST_PARTS)==3):
                                GENPOSTCONFIG="Default" if WHOLEPOST_PARTS[1].lower()=="default" else WHOLEPOST_PARTS[1]
                                GENPOSTCONFIGEVT="Default" if WHOLEPOST_PARTS[2].lower()=="default" else WHOLEPOST_PARTS[2]
                        elif(len(WHOLEPOST_PARTS)==4):
                                GENPOSTCONFIG="Default" if WHOLEPOST_PARTS[1].lower()=="default" else WHOLEPOST_PARTS[1]
                                GENPOSTCONFIGEVT="Default" if WHOLEPOST_PARTS[2].lower()=="default" else WHOLEPOST_PARTS[2]
                                GENPOSTCONFIGDEC="Default" if WHOLEPOST_PARTS[3].lower()=="default" else WHOLEPOST_PARTS[3]
                        elif(len(WHOLEPOST_PARTS)==1):
                                GENPOST=WHOLEPOST

                elif str(parts[0]).upper()=="CUSTOM_MAKEMC" :
                        CUSTOM_MAKEMC=rm_comments[0].strip()
                elif str(parts[0]).upper()=="CUSTOM_GCONTROL" :
                        CUSTOM_GCONTROL=rm_comments[0].strip()
                elif str(parts[0]).upper()=="BKG" :
                        bkg_parts=rm_comments[0].strip().split("+")
                        #print bkg_parts
                        for part in bkg_parts:
                                subparts=part.split(":")
                                if len(subparts)>2:
                                        print( "Error in BKG Parsing: "+part)
                                        return
                                if subparts[0].upper() == "TAGONLY":
                                        BGTAGONLY=1
                                        if BGFOLD == "DEFAULT":
                                                BGFOLD="TagOnly"
                                        if len(subparts)==2:
                                                BGRATE=subparts[1]

                                elif subparts[0].upper() == "BEAMPHOTONS":
                                        #print subparts
                                        BGFOLD=subparts[0]
                                        if len(subparts)==2:
                                                BGRATE=subparts[1]
                                elif subparts[0].upper() == "RANDOM" or subparts[0].upper() == "DEFAULT":
                                        BGFOLD=subparts[0]
                                        if len(subparts)==2:
                                                RANDBGTAG=subparts[1]
                                elif subparts[0].upper() == "NOTAG":
                                        SMEAR_NOTAG="1"
                                else:
                                        BGFOLD=part

                elif str(parts[0]).upper()=="EBEAM_ENERGY" :
                        eBEAM_ENERGY=rm_comments[0].strip()
                elif str(parts[0]).upper()=="EBEAM_CURRENT" :
                        eBEAM_CURRENT=rm_comments[0].strip()
                elif str(parts[0]).upper()=="COHERENT_PEAK" :
                        COHERENT_PEAK=rm_comments[0].strip()
                elif str(parts[0]).upper()=="RADIATOR_THICKNESS" :
                        RADIATOR_THICKNESS=rm_comments[0].strip()
                elif str(parts[0]).upper()=="GEN_MIN_ENERGY" :
                        MIN_GEN_ENERGY=rm_comments[0].strip()
                elif str(parts[0]).upper()=="GEN_MAX_ENERGY" :
                        MAX_GEN_ENERGY=rm_comments[0].strip()
                elif str(parts[0]).upper()=="UPPER_VERTEX_INDICES" :
                        UPPER_VERTEX_INDICES=rm_comments[0].strip()
                elif str(parts[0]).upper()=="LOWER_VERTEX_INDICES" :
                        LOWER_VERTEX_INDICES=rm_comments[0].strip()
                elif str(parts[0]).upper()=="TAG" :
                        TAGSTR=rm_comments[0].strip()
                elif str(parts[0]).upper()=="CUSTOM_PLUGINS" :
                        CUSTOM_PLUGINS=rm_comments[0].strip()
                elif str(parts[0]).upper()=="CUSTOM_ANA_PLUGINS" :
                        CUSTOM_ANA_PLUGINS=rm_comments[0].strip()
                elif str(parts[0]).upper()=="BATCH_SYSTEM" :
                        batch_sys_parts=rm_comments[0].strip().split(":")
                        BATCHSYS=batch_sys_parts[0]
                        if len(batch_sys_parts) > 1 :
                                QUEUENAME=batch_sys_parts[1]
                elif str(parts[0]).upper()=="RUNNING_DIRECTORY" :
                        RUNNING_DIR=rm_comments[0].strip()
                elif str(parts[0]).upper()=="RECON_CALIBTIME" :
                        RECON_CALIBTIME=rm_comments[0].strip()
                elif str(parts[0]).upper()=="VARIATION":
                        #print(parts)
                        #print rm_comments
                        recomb="=".join(parts)
                        print(recomb)
                        space_parts=recomb.split(" ")
                        if ( len(space_parts)==2 ) :
                                VERSION=space_parts[0].split("=")[1] #str(parts[1]).split("calibtime")[0].split("#")[0].strip()
                                CALIBTIME=space_parts[1].split("=")[1] #str(parts[2]).split("#")[0].strip()
                        elif ( len(space_parts)==1):
                                VERSION=space_parts[0].split("=")[1]
                        else:
                                print("VARIATION improperly set and is not parseable.  Please configure the VARIATION properly in",CONFIG_FILE)
                                exit(1)

                        #print("ver/calib:",VERSION,CALIBTIME[0])
                        if VERSION=="" or len(VERSION.split(" ")) != 1 or CALIBTIME=="timegoeshere": #or (CALIBTIME != "notime" and not (CALIBTIME[0]).isnumeric())
                                print("VARIATION improperly set.  Please configure the VARIATION properly in",CONFIG_FILE)
                                exit(1)

                elif str(parts[0]).upper()=="CCDBSQLITEPATH":
                        ccdbSQLITEPATH=rm_comments[0].strip()
                elif str(parts[0]).upper()=="RCDBSQLITEPATH" :
                        rcdbSQLITEPATH=rm_comments[0].strip()
                elif str(parts[0]).upper()=="RCDB_QUERY" :
                        #print line.split("#")[0].find('=')
                        query=line.split("#")[0][line.split("#")[0].find('=')+1:]
                        RCDB_QUERY=query
                elif str(parts[0]).upper()=="NOSECONDARIES" :
                        NOSECONDARIES=rm_comments[0].strip()
                elif str(parts[0]).upper()=="NOSIPMSATURATION" :
                        NOSIPMSATURATION=rm_comments[0].strip()
                elif str(parts[0]).upper()=="FLUX_TO_GEN":
                        fluxbits=rm_comments[0].strip().split(":")
                        if( len(fluxbits) == 2 ): # use flux histogram file
                                FLUX_TO_GEN=fluxbits[0]
                                FLUX_HIST=fluxbits[1]
                        elif ( len(fluxbits) == 1):
                                if( str(fluxbits[0]).upper()=="COBREMS"): # COBREM calculation
                                        FLUX_TO_GEN="cobrems"
                elif str(parts[0]).upper()=="POL_TO_GEN":
                        polbits=rm_comments[0].strip().split(":")
                        if( len(polbits) == 2 ):
                                POL_TO_GEN=polbits[0]
                                POL_HIST=polbits[1]
                        elif (len(polbits)==1):
                                POL_TO_GEN=polbits[0]
                                if (FLUX_TO_GEN == "cobrems"):
                                        POL_HIST="cobrems"

                else:
                        print( "unknown config parameter!! "+str(parts[0]))

        if EXPERIMENT == "GlueX" and PROJECT != "gluex": #set EXPERIMENT if not set and not GlueX
                EXPERIMENT = PROJECT

        LOG_DIR = DATA_OUTPUT_BASE_DIR  #set LOG_DIR=DATA_OUTPUT_BASE_DIR
        if(GENCONFIG==""):
                GENCONFIG = "NA"
        #loop over command line arguments
        for argu in args:
                argfound=0
                flag=argu.split("=")
                #redundat check to jump over the first 4 arguments
                if(len(flag)<2):
                        continue
                else:#toggle the flags as user defines
                        if flag[0]=="variation":
                                argfound=1

                                VERSION=flag[1]
                                CALIBTIME="notime"
 #                               for part in range(2,len(flag)):
  #                                      VERSION+="="+flag[part]
                        if flag[0]=="calibtime":
                                argfound=1
                                CALIBTIME=flag[1]
                        if flag[0]=="per_file":
                                argfound=1
                                PERFILE=int(flag[1])
                        if flag[0]=="base_file_number":
                                argfound=1
                                BASEFILENUM=int(flag[1])
                        if flag[0]=="generate":
                                argfound=1
                                GENR=int(flag[1])
                        if flag[0]=="geant":
                                argfound=1
                                GEANT=int(flag[1])
                        if flag[0]=="mcsmear":
                                argfound=1
                                SMEAR=int(flag[1])
                        if flag[0]=="recon":
                                argfound=1
                                RECON=int(flag[1])
                        if flag[0]=="cleangenerate":
                                argfound=1
                                CLEANGENR=int(flag[1])
                        if flag[0]=="cleangeant":
                                argfound=1
                                CLEANGEANT=int(flag[1])
                        if flag[0]=="cleanmcsmear":
                                argfound=1
                                CLEANSMEAR=int(flag[1])
                        if flag[0]=="cleanrecon":
                                argfound=1
                                CLEANRECON=int(flag[1])
                        if flag[0]=="batch":
                                argfound=1
                                BATCHRUN=int(flag[1])
                        if flag[0]=="numthreads":
                                argfound=1
                                NCORES=str(flag[1])
                        if flag[0]=="logdir":
                                argfound=1
                                LOG_DIR=str(flag[1])
                        if flag[0]=="projid":
                                argfound=1
                                PROJECT_ID=str(flag[1])
                        if flag[0]=="shell":
                                argfound=1
                                SHELL_TO_USE=str(flag[1])
                        if flag[0]=="submitter":
                                argfound=1
                                IS_SUBMITTER=str(flag[1])
                        if flag[0]=="tobundle":
                                argfound=1
                                #print("found tobundle",str(flag[1]))
                                if(str(flag[1])=="1"):
                                        TO_BUNDLE=True
                        if argfound==0:
                                print( "WARNING OPTION: "+argu+" NOT FOUND!")

        if DATA_OUTPUT_BASE_DIR == "UNKNOWN_LOCATION":
                print( "I doubt that the system will find the output directory: "+DATA_OUTPUT_BASE_DIR+" so I am saving you the embarassment of trying and stopping this now")
                return

        print("WILL BE BUNDLED",TO_BUNDLE)

        name_breakdown=GENCONFIG.split("/")
        CHANNEL = name_breakdown[len(name_breakdown)-1].split(".")[0]

        #print a line indicating Batch or Local run
        if BATCHRUN == 0 or BATCHSYS=="NULL":
                print( "Locally simulating "+args[2]+" "+CHANNEL+" Events")
        else:
                print( "Creating "+WORKFLOW+" to simulate "+args[2]+" "+CHANNEL+" Events")
        # CREATE WORKFLOW

        #username = getpass.getuser()
        #print(username)
        #exit

        #calculate files needed to gen
        FILES_TO_GEN=EVTS/PERFILE
        REMAINING_GEN=EVTS%PERFILE

        #DETECT LOGIN SHELL AND PICK THE RIGHT SCRIPT TO RUN
        SCRIPT_TO_RUN=os.environ.get('MCWRAPPER_CENTRAL')

        script_to_use = "/MakeMC.csh"

        loginSHELL="bash"

        try:
                loginSHELL=environ['SHELL'].split("/")
        except:
                pass

        if loginSHELL[len(loginSHELL)-1]=="bash" or ( BATCHSYS.upper() == "OSG" and int(BATCHRUN) != 0) or SHELL_TO_USE=="bash" :
                script_to_use = "/MakeMC.sh"
        elif loginSHELL[len(loginSHELL)-1]=="zsh" or SHELL_TO_USE=="zcsh":
                script_to_use = "/MakeMC.sh"

        SCRIPT_TO_RUN+=script_to_use

        if ".jlab.org" in socket.gethostname() :
                LOCATION="JLAB"

        if len(CUSTOM_MAKEMC)!= 0 and CUSTOM_MAKEMC != "DEFAULT":
                SCRIPT_TO_RUN=CUSTOM_MAKEMC

        #if (BATCHSYS.upper() == "OSG" or BATCHSYS.upper() == "SWIF") and int(BATCHRUN) != 0 and ccdbSQLITEPATH=="no_sqlite":
        if (BATCHSYS.upper() == "OSG") and int(BATCHRUN) != 0 and ccdbSQLITEPATH=="no_sqlite":
                ccdbSQLITEPATH="batch_default"

        if (BATCHSYS.upper() == "SWIF") and int(BATCHRUN) != 0 and ccdbSQLITEPATH=="no_sqlite":
                ccdbSQLITEPATH="jlab_batch_default"
                LOCATION="JLAB"
        if (BATCHSYS.upper() == "SWIF2") and int(BATCHRUN) != 0 and ccdbSQLITEPATH=="no_sqlite":
                ccdbSQLITEPATH="jlab_batch_default"
                LOCATION="JLAB"
        #if (BATCHSYS.upper() == "OSG" or BATCHSYS.upper() == "SWIF") and int(BATCHRUN) != 0 and rcdbSQLITEPATH=="no_sqlite":
        if (BATCHSYS.upper() == "OSG" ) and int(BATCHRUN) != 0 and rcdbSQLITEPATH=="no_sqlite":
                rcdbSQLITEPATH="batch_default"
                LOCATION="OSG"
        if str(SCRIPT_TO_RUN) == "None":
                print( "MCWRAPPER_CENTRAL not set")
                return

        outdir=DATA_OUTPUT_BASE_DIR

        #if local run set out directory to cwd
        if outdir[len(outdir)-1] != "/" :
                outdir+= "/"

        #for every needed file call the script with the right options

        #need two loops 1) for when RUNNUM is a number and 2) when it contains a "-" as in 11366-11555 or RunPeriod2017-02
        # for 2) use rcdb to get a list of the runs of a runperiod and amount of data.  Normalize number of events. Loop through list calling with the runnumbers from rcdb and their normalized num_events*requested events
        RunType=str(RUNNUM).split("-")


        COMMAND_dict={'batchrun':str(BATCHRUN)}
        COMMAND_dict['environment_file']=ENVFILE
        COMMAND_dict['ana_environment_file']=ANAENVFILE
        COMMAND_dict['generator_config']=GENCONFIG
        COMMAND_dict['output_directory']=str(outdir)
        COMMAND_dict['run_number']=str(RUNNUM)
        COMMAND_dict['file_number']=str(BASEFILENUM)
        COMMAND_dict['num_events']=str(EVTS)
        COMMAND_dict['jana_calib_context']=str(VERSION)
        COMMAND_dict['jana_calibtime']=str(CALIBTIME)
        COMMAND_dict['do_gen']=str(GENR)
        COMMAND_dict['do_geant']=str(GEANT)
        COMMAND_dict['do_mcsmear']=str(SMEAR)
        COMMAND_dict['do_recon']=str(RECON)
        COMMAND_dict['clean_gen']=str(CLEANGENR)
        COMMAND_dict['clean_geant']=str(CLEANGEANT)
        COMMAND_dict['clean_mcsmear']=str(CLEANSMEAR)
        COMMAND_dict['clean_recon']=str(CLEANRECON)
        COMMAND_dict['batch_system']=str(BATCHSYS)
        COMMAND_dict['num_cores']=str(NCORES).split(':')[-1]
        COMMAND_dict['generator']=str(GENERATOR)
        COMMAND_dict['geant_version']=str(GEANTVER)
        COMMAND_dict['background_to_include']=str(BGFOLD)
        COMMAND_dict['custom_Gcontrol']=str(CUSTOM_GCONTROL)
        COMMAND_dict['eBeam_energy']=str(eBEAM_ENERGY)
        COMMAND_dict['coherent_peak']=str(COHERENT_PEAK)
        COMMAND_dict['min_generator_energy']=str(MIN_GEN_ENERGY)
        COMMAND_dict['max_generator_energy']=str(MAX_GEN_ENERGY)
        COMMAND_dict['upper_vertex_indices']=str(UPPER_VERTEX_INDICES)
        COMMAND_dict['lower_vertex_indices']=str(LOWER_VERTEX_INDICES)
        COMMAND_dict['custom_tag_string']=str(TAGSTR)
        COMMAND_dict['custom_plugins']=str(CUSTOM_PLUGINS)
        COMMAND_dict['custom_ana_plugins']=str(CUSTOM_ANA_PLUGINS)
        COMMAND_dict['events_per_file']=str(PERFILE)
        COMMAND_dict['running_directory']=str(RUNNING_DIR)
        COMMAND_dict['ccdb_sqlite_path']=str(ccdbSQLITEPATH)
        COMMAND_dict['rcdb_sqlite_path']=str(rcdbSQLITEPATH)
        COMMAND_dict['background_tagger_only']=str(BGTAGONLY)
        COMMAND_dict['radiator_thickness']=str(RADIATOR_THICKNESS)
        COMMAND_dict['background_rate']=str(BGRATE)
        COMMAND_dict['random_background_tag']=str(RANDBGTAG)
        COMMAND_dict['recon_calibtime']=str(RECON_CALIBTIME)
        COMMAND_dict['no_geant_secondaries']=str(NOSECONDARIES)
        COMMAND_dict['mcwrapper_version']=str(MCWRAPPER_VERSION)
        COMMAND_dict['no_bcal_sipm_saturation']=str(NOSIPMSATURATION)
        COMMAND_dict['flux_to_generate']=str(FLUX_TO_GEN)
        COMMAND_dict['flux_histogram']=str(FLUX_HIST)
        COMMAND_dict['polarization_to_generate']=str(POL_TO_GEN)
        COMMAND_dict['polarization_histogram']=str(POL_HIST)
        COMMAND_dict['eBeam_current']=str(eBEAM_CURRENT)
        COMMAND_dict['experiment']=str(EXPERIMENT)

        COMMAND_dict['num_rand_trigs']=str(RANDOM_NUM_EVT)
        COMMAND_dict['location']=str(LOCATION)
        COMMAND_dict['generator_post']=str(GENPOST)
        COMMAND_dict['generator_post_config']=str(GENPOSTCONFIG)
        COMMAND_dict['generator_post_configevt']=str(GENPOSTCONFIGEVT)
        COMMAND_dict['generator_post_configdec']=str(GENPOSTCONFIGDEC)
        COMMAND_dict['geant_vertex_area']=str(VERTEX_AREA)
        COMMAND_dict['geant_vertex_length']=str(VERTEX_LENGTH)
        COMMAND_dict['mcsmear_notag']=str(SMEAR_NOTAG)
        COMMAND_dict['project_directory_name']=str(DATA_OUTPUT_BASE_DIR)


        if(COMMAND_dict['generator'][:4]=="file:" and len(RunType) != 1):
                print("ERROR: MCwrapper currently does not support taking a monolithic file and converting it into a range of runs.")
                exit(1)

        #The submitter grabs a single unattempted job and submits it.  Always a single runnumber
        #
        #print(COMMAND_dict)
        if str(IS_SUBMITTER) == "1":
                if BGFOLD == "Random" or BGFOLD=="DEFAULT" or BGFOLD[0:3] == "loc":
                        RANDOM_NUM_EVT=GetRandTrigNums(BGFOLD,RANDBGTAG,BATCHSYS,RUNNUM)
                        COMMAND_dict['num_rand_trigs']=str(RANDOM_NUM_EVT)

                if BATCHRUN == 0 or BATCHSYS.upper()=="NULL":
                        os.system(str(SCRIPT_TO_RUN)+" "+getCommandString(COMMAND_dict,"INTERACTIVE"))
                else:
                        if PROJECT_ID != 0: #below only valid for initial atomization
                                print("SELECT ID FROM Jobs WHERE Project_ID="+str(PROJECT_ID)+" && RunNumber="+str(RUNNUM)+" && FileNumber="+str(BASEFILENUM)+" && NumEvts="+str(EVTS))
                                findmyjob="SELECT ID FROM Jobs WHERE Project_ID="+str(PROJECT_ID)+" && RunNumber="+str(RUNNUM)+" && FileNumber="+str(BASEFILENUM)+" && NumEvts="+str(EVTS)
                                dbcursor.execute(findmyjob)
                                MYJOB = dbcursor.fetchall()
                                print(len(MYJOB) )
                        if len(MYJOB) == 0:
                                if BATCHSYS.upper()=="SWIF":
                                        #status = subprocess.call("swif create "+WORKFLOW,shell=True)
                                        swif_add_job(WORKFLOW, RUNNUM, BASEFILENUM,str(SCRIPT_TO_RUN),COMMAND_dict,VERBOSE,PROJECT,TRACK,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR, PROJECT_ID)
                                        swifrun = "swif run "+WORKFLOW
                                        subprocess.call(swifrun.split(" "))
                                elif BATCHSYS.upper()=="SWIF2":
                                        #status = subprocess.call("swif2 create "+WORKFLOW,shell=True)
                                        swif2_add_job(WORKFLOW, RUNNUM, BASEFILENUM,str(SCRIPT_TO_RUN),COMMAND_dict,VERBOSE,ACCOUNT,PARTITION,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR,LOG_DIR, PROJECT_ID)
                                        swifrun = "swif2 run "+WORKFLOW
                                        subprocess.call(swifrun.split(" "))
                                elif BATCHSYS.upper()=="SWIF2CONT":
                                        #status = subprocess.call("swif2 create "+WORKFLOW,shell=True)
                                        swif2cont_add_job(WORKFLOW, RUNNUM, BASEFILENUM,str(SCRIPT_TO_RUN),COMMAND_dict,VERBOSE,ACCOUNT,PARTITION,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR,LOG_DIR, PROJECT_ID)
                                        swifrun = "swif2 run "+WORKFLOW
                                        subprocess.call(swifrun.split(" "))
                                elif BATCHSYS.upper()=="QSUB":
                                        qsub_add_job(VERBOSE, WORKFLOW, RUNNUM, BASEFILENUM, SCRIPT_TO_RUN, COMMAND_dict, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, RAM, QUEUENAME, LOG_DIR, PROJECT_ID )
                                elif BATCHSYS.upper()=="CONDOR":
                                        condor_add_job(VERBOSE, WORKFLOW, RUNNUM, BASEFILENUM, SCRIPT_TO_RUN, COMMAND_dict, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, PROJECT_ID, CONDOR_MAGIC )
                                elif BATCHSYS.upper()=="OSG":
                                        OSG_add_job(VERBOSE, WORKFLOW, RUNNUM, BASEFILENUM, SCRIPT_TO_RUN, COMMAND_dict, NCORES, RAM, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID,TO_BUNDLE )
                                elif BATCHSYS.upper()=="SLURMCONT":
                                        SLURMcont_add_job(VERBOSE, WORKFLOW, RUNNUM, BASEFILENUM, SCRIPT_TO_RUN, COMMAND_dict, NCORES, RAM,DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID )
                                elif BATCHSYS.upper()=="SLURM":
                                        SLURM_add_job(VERBOSE, WORKFLOW, RUNNUM, BASEFILENUM, SCRIPT_TO_RUN, COMMAND_dict, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID )
        else:
                #print("NOT THE SUBMITTER")
                #print(len(RunType))
                if len(RunType) != 1 : #RUN RANGE GIVEN
                        event_sum=0.
                        #Make python rcdb calls to form the vector
                        db = rcdb.RCDBProvider("mysql://rcdb@hallddb.jlab.org/rcdb")
                        ccdb_conn = LoadCCDB()

                        runlow=0
                        runhigh=0

                        if RunType[0] != "RunPeriod":
                                runlow=RunType[0].lstrip("0")
                                runhigh=RunType[1].lstrip("0")
                        else:
                                cnx = mysql.connector.connect(user='ccdb_user', database='ccdb', host='hallddb.jlab.org')
                                cursor = cnx.cursor()

                                runrange_name=""
                                for npart in RunType:
                                        if npart=="RunPeriod":
                                                continue
                                        else:
                                                runrange_name=runrange_name+npart

                                cursor.execute("select runMin,runMax from runRanges where name = '"+runrange_name+"'")
                                runRange = cursor.fetchall()
                                runlow=runRange[0][0]
                                runhigh=runRange[0][1]
                                print( runRange)
                                #cursor.close()
                                #cnx.close()
                                print( str(runlow)+"-->"+str(runhigh))

                        query_to_do="@is_production and @status_approved"
                        print("RCDB_QUERY IS: "+str(RCDB_QUERY))
                        if(RCDB_QUERY!=""):
                                query_to_do=RCDB_QUERY

                        print(str(runlow)+"------->"+str(runhigh))
                        table = db.select_runs(str(query_to_do),runlow,runhigh).get_values(['event_count','polarimeter_converter'],True)
                        print(table)
                        #print len(table)

                        print("\nComputing flux from CCDB for all runs in the requested range, this may take a minute...\n")
                        fluxes = []
                        flux_sum = 0
                        for runs in table:
                                print(runs)
                                if len(table)<=1:
                                        fluxes.append(0)
                                        break
                                event_sum = event_sum + runs[1]

                                # compute flux in generated beam energy range
                                flux = calcFluxCCDB(ccdb_conn, runs, float(MIN_GEN_ENERGY), float(MAX_GEN_ENERGY)) / 1.e9
                                print(flux)
                                fluxes.append(flux)
                                flux_sum = flux_sum + flux

                        print("Events from rcdb: "+str(event_sum))
                        if(event_sum==0 and PROJECT_ID>0):
                                print("No events found in the requested range matching the RCDB query, exiting")
                                email_no_events(PROJECT_ID)


                        print("Flux from ccdb: "+str(flux_sum))
                        sum2=0.
                        sum2_trig=0.
                        for runs,flux in zip(table,fluxes): #do for each job
                                #print(runs[0])
                                if len(table) <= 1:
                                        break
                                #num_events_this_run_trig=int(((float(runs[1])/float(event_sum))*EVTS)+.5)
                                #sum2_trig=sum2_trig+int(((float(runs[1])/float(event_sum))*EVTS)+.5)
                                num_events_this_run=int(((flux/flux_sum)*EVTS)+.5)
                                sum2=sum2+int(((flux/flux_sum)*EVTS)+.5)
                                #print(runs[0],num_events_this_run)
                                #continue

                                if num_events_this_run == 0:
                                        continue

                               #do for each file needed
                                FILES_TO_GEN_this_run=num_events_this_run/PERFILE
                                REMAINING_GEN_this_run=num_events_this_run%PERFILE

                                for FILENUM_this_run in range(1, FILES_TO_GEN_this_run + 2):
                                        num_this_file=PERFILE

                                        if FILENUM_this_run == FILES_TO_GEN_this_run +1:
                                                num_this_file=REMAINING_GEN_this_run

                                        if num_this_file == 0:
                                                continue

                                        COMMAND_dict['run_number']=str(runs[0])
                                        COMMAND_dict['file_number']=str(BASEFILENUM+FILENUM_this_run+-1)
                                        COMMAND_dict['num_events']=str(num_this_file)
                                        if BGFOLD == "Random" or BGFOLD=="DEFAULT" or BGFOLD[0:3] == "loc":
                                                RANDOM_NUM_EVT=GetRandTrigNums(BGFOLD,RANDBGTAG,BATCHSYS,runs[0])
                                                COMMAND_dict['num_rand_trigs']=str(RANDOM_NUM_EVT)
                                        COMMAND=getCommandString(COMMAND_dict,"NONSUB") #str(BATCHRUN)+" "+ENVFILE+" "+GENCONFIG+" "+str(outdir)+" "+str(runs[0])+" "+str(BASEFILENUM+FILENUM_this_run+-1)+" "+str(num_this_file)+" "+str(VERSION)+" "+str(CALIBTIME)+" "+str(GENR)+" "+str(GEANT)+" "+str(SMEAR)+" "+str(RECON)+" "+str(CLEANGENR)+" "+str(CLEANGEANT)+" "+str(CLEANSMEAR)+" "+str(CLEANRECON)+" "+str(BATCHSYS)+" "+str(NCORES).split(':')[-1]+" "+str(GENERATOR)+" "+str(GEANTVER)+" "+str(BGFOLD)+" "+str(CUSTOM_GCONTROL)+" "+str(eBEAM_ENERGY)+" "+str(COHERENT_PEAK)+" "+str(MIN_GEN_ENERGY)+" "+str(MAX_GEN_ENERGY)+" "+str(TAGSTR)+" "+str(CUSTOM_PLUGINS)+" "+str(CUSTOM_ANA_PLUGINS)+" "+str(PERFILE)+" "+str(RUNNING_DIR)+" "+str(ccdbSQLITEPATH)+" "+str(rcdbSQLITEPATH)+" "+str(BGTAGONLY)+" "+str(RADIATOR_THICKNESS)+" "+str(BGRATE)+" "+str(RANDBGTAG)+" "+str(RECON_CALIBTIME)+" "+str(NOSECONDARIES)+" "+str(MCWRAPPER_VERSION)+" "+str(NOSIPMSATURATION)+" "+str(FLUX_TO_GEN)+" "+str(FLUX_HIST)+" "+str(POL_TO_GEN)+" "+str(POL_HIST)+" "+str(eBEAM_CURRENT)+" "+str(PROJECT)


                                        if BATCHRUN == 0 or BATCHSYS.upper()=="NULL":
                                                #print str(runs[0])+" "+str(BASEFILENUM+FILENUM_this_run+-1)+" "+str(num_this_file)
                                                os.system(str(SCRIPT_TO_RUN)+" "+getCommandString(COMMAND_dict,"INTERACTIVE"))
                                        else:
                                                if PROJECT_ID != 0:
                                                        print("SELECT ID FROM Jobs WHERE Project_ID="+str(PROJECT_ID)+" && RunNumber="+str(runs[0])+" && FileNumber="+str(BASEFILENUM+FILENUM_this_run+-1)+" && NumEvts="+str(num_this_file))
                                                        findmyjob="SELECT ID FROM Jobs WHERE Project_ID="+str(PROJECT_ID)+" && RunNumber="+str(runs[0])+" && FileNumber="+str(BASEFILENUM+FILENUM_this_run+-1)+" && NumEvts="+str(num_this_file)
                                                        dbcursor.execute(findmyjob)
                                                        MYJOB = dbcursor.fetchall()
                                                        print(len(MYJOB))
                                                if len(MYJOB) == 0:
                                                        if BATCHSYS.upper()=="SWIF":
                                                                #status = subprocess.call("swif create "+WORKFLOW,shell=True)
                                                                swif_add_job(WORKFLOW, runs[0], BASEFILENUM+FILENUM_this_run+-1,str(SCRIPT_TO_RUN),COMMAND_dict,VERBOSE,PROJECT,TRACK,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR, PROJECT_ID)
                                                        elif BATCHSYS.upper()=="SWIF2":
                                                                #status = subprocess.call("swif2 create "+WORKFLOW,shell=True)
                                                                swif2_add_job(WORKFLOW, runs[0], BASEFILENUM+FILENUM_this_run+-1,str(SCRIPT_TO_RUN),COMMAND_dict,VERBOSE,ACCOUNT,PARTITION,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR,LOG_DIR, PROJECT_ID)
                                                        elif BATCHSYS.upper()=="SWIF2CONT":
                                                                #status = subprocess.call("swif2 create "+WORKFLOW,shell=True)
                                                                swif2cont_add_job(WORKFLOW, runs[0], BASEFILENUM+FILENUM_this_run+-1,str(SCRIPT_TO_RUN),COMMAND_dict,VERBOSE,ACCOUNT,PARTITION,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR,LOG_DIR, PROJECT_ID)
                                                        elif BATCHSYS.upper()=="QSUB":
                                                                qsub_add_job(VERBOSE, WORKFLOW, runs[0], BASEFILENUM+FILENUM_this_run+-1, SCRIPT_TO_RUN, COMMAND_dict, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, RAM, QUEUENAME, LOG_DIR, PROJECT_ID )
                                                        elif BATCHSYS.upper()=="CONDOR":
                                                                condor_add_job(VERBOSE, WORKFLOW, runs[0], BASEFILENUM+FILENUM_this_run+-1, SCRIPT_TO_RUN, COMMAND_dict, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, PROJECT_ID, CONDOR_MAGIC )
                                                        elif BATCHSYS.upper()=="OSG":
                                                                OSG_add_job(VERBOSE, WORKFLOW, runs[0], BASEFILENUM+FILENUM_this_run+-1, SCRIPT_TO_RUN, COMMAND_dict, NCORES, RAM, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID, TO_BUNDLE)
                                                        elif BATCHSYS.upper()=="SLURMCONT":
                                                                SLURM_add_job(VERBOSE, WORKFLOW, runs[0], BASEFILENUM+FILENUM_this_run+-1, SCRIPT_TO_RUN, COMMAND_dict, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID )
                                                        elif BATCHSYS.upper()=="SLURM":
                                                                SLURM_add_job(VERBOSE, WORKFLOW, runs[0], BASEFILENUM+FILENUM_this_run+-1, SCRIPT_TO_RUN, COMMAND_dict, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID )

                else:
                        #if FILES_TO_GEN >= 500 and ( ccdbSQLITEPATH == "no_sqlite" or rcdbSQLITEPATH == "no_sqlite"):
                        #        print( "This job has >500 subjobs and risks ddosing the servers.  Please use sqlite or request again with a larger per file. ")
                        #        return

                        for FILENUM in range(1, FILES_TO_GEN + 2):
                                num=PERFILE
                                #last file gets the remainder
                                if FILENUM == FILES_TO_GEN +1:
                                        num=REMAINING_GEN
                                #if ever asked to generate 0 events....just don't
                                if num == 0:
                                        continue

                                COMMAND_dict['run_number']=str(RUNNUM)
                                COMMAND_dict['file_number']=str(BASEFILENUM+FILENUM+-1)
                                COMMAND_dict['num_events']=str(num)

                                if BGFOLD == "Random" or BGFOLD=="DEFAULT" or BGFOLD[0:3] == "loc":
                                        RANDOM_NUM_EVT=GetRandTrigNums(BGFOLD,RANDBGTAG,BATCHSYS,RUNNUM)
                                        COMMAND_dict['num_rand_trigs']=str(RANDOM_NUM_EVT)

                                COMMAND=getCommandString(COMMAND_dict,"INTERACTIVE") #str(BATCHRUN)+" "+ENVFILE+" "+GENCONFIG+" "+str(outdir)+" "+str(RUNNUM)+" "+str(BASEFILENUM+FILENUM+-1)+" "+str(num)+" "+str(VERSION)+" "+str(CALIBTIME)+" "+str(GENR)+" "+str(GEANT)+" "+str(SMEAR)+" "+str(RECON)+" "+str(CLEANGENR)+" "+str(CLEANGEANT)+" "+str(CLEANSMEAR)+" "+str(CLEANRECON)+" "+str(BATCHSYS).upper()+" "+str(NCORES).split(':')[-1]+" "+str(GENERATOR)+" "+str(GEANTVER)+" "+str(BGFOLD)+" "+str(CUSTOM_GCONTROL)+" "+str(eBEAM_ENERGY)+" "+str(COHERENT_PEAK)+" "+str(MIN_GEN_ENERGY)+" "+str(MAX_GEN_ENERGY)+" "+str(TAGSTR)+" "+str(CUSTOM_PLUGINS)+" "+str(CUSTOM_ANA_PLUGINS)+" "+str(PERFILE)+" "+str(RUNNING_DIR)+" "+str(ccdbSQLITEPATH)+" "+str(rcdbSQLITEPATH)+" "+str(BGTAGONLY)+" "+str(RADIATOR_THICKNESS)+" "+str(BGRATE)+" "+str(RANDBGTAG)+" "+str(RECON_CALIBTIME)+" "+str(NOSECONDARIES)+" "+str(MCWRAPPER_VERSION)+" "+str(NOSIPMSATURATION)+" "+str(FLUX_TO_GEN)+" "+str(FLUX_HIST)+" "+str(POL_TO_GEN)+" "+str(POL_HIST)+" "+str(eBEAM_CURRENT)+" "+str(PROJECT)

                                #either call MakeMC.csh or add a job depending on swif flag
                                if BATCHRUN == 0 or BATCHSYS.upper()=="NULL":
                                        os.system(str(SCRIPT_TO_RUN)+" "+COMMAND)
                                else:
                                        if PROJECT_ID != 0:
                                                print("SELECT ID FROM Jobs WHERE Project_ID="+str(PROJECT_ID)+" && RunNumber="+str(RUNNUM)+" && FileNumber="+str(BASEFILENUM+FILENUM+-1)+" && NumEvts="+str(num))
                                                findmyjob="SELECT ID FROM Jobs WHERE Project_ID="+str(PROJECT_ID)+" && RunNumber="+str(RUNNUM)+" && FileNumber="+str(BASEFILENUM+FILENUM+-1)+" && NumEvts="+str(num)
                                                dbcursor.execute(findmyjob)
                                                MYJOB = dbcursor.fetchall()
                                                print(len(MYJOB))
                                        if len(MYJOB) == 0:
                                                if BATCHSYS.upper()=="SWIF":
                                                        #status = subprocess.call("swif create "+WORKFLOW,shell=True)
                                                        swif_add_job(WORKFLOW, RUNNUM, BASEFILENUM+FILENUM+-1,str(SCRIPT_TO_RUN),COMMAND_dict,VERBOSE,PROJECT,TRACK,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR, PROJECT_ID)
                                                elif BATCHSYS.upper()=="SWIF2":
                                                        #status = subprocess.call("swif2 create "+WORKFLOW,shell=True)
                                                        swif2_add_job(WORKFLOW, RUNNUM, BASEFILENUM+FILENUM+-1,str(SCRIPT_TO_RUN),COMMAND_dict,VERBOSE,ACCOUNT,PARTITION,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR,LOG_DIR, PROJECT_ID)
                                                elif BATCHSYS.upper()=="SWIF2CONT":
                                                        #status = subprocess.call("swif2 create "+WORKFLOW,shell=True)
                                                        swif2cont_add_job(WORKFLOW, RUNNUM, BASEFILENUM+FILENUM+-1,str(SCRIPT_TO_RUN),COMMAND_dict,VERBOSE,ACCOUNT,PARTITION,NCORES,DISK,RAM,TIMELIMIT,OS,DATA_OUTPUT_BASE_DIR,LOG_DIR, PROJECT_ID)
                                                elif BATCHSYS.upper()=="QSUB":
                                                        qsub_add_job(VERBOSE, WORKFLOW, RUNNUM, BASEFILENUM+FILENUM+-1, SCRIPT_TO_RUN, COMMAND_dict, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, RAM, QUEUENAME, LOG_DIR, PROJECT_ID )
                                                elif BATCHSYS.upper()=="CONDOR":
                                                        condor_add_job(VERBOSE, WORKFLOW, RUNNUM, BASEFILENUM+FILENUM+-1, SCRIPT_TO_RUN, COMMAND_dict, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, PROJECT_ID, CONDOR_MAGIC )
                                                elif BATCHSYS.upper()=="OSG":
                                                        OSG_add_job(VERBOSE, WORKFLOW, RUNNUM, BASEFILENUM+FILENUM+-1, SCRIPT_TO_RUN, COMMAND_dict, NCORES, RAM, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID, TO_BUNDLE )
                                                elif BATCHSYS.upper()=="SLURMCONT":
                                                        SLURMcont_add_job(VERBOSE, WORKFLOW, RUNNUM, BASEFILENUM+FILENUM+-1, SCRIPT_TO_RUN, COMMAND_dict, NCORES, RAM, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID )
                                                elif BATCHSYS.upper()=="SLURM":
                                                        SLURM_add_job(VERBOSE, WORKFLOW, RUNNUM, BASEFILENUM+FILENUM+-1, SCRIPT_TO_RUN, COMMAND_dict, NCORES, DATA_OUTPUT_BASE_DIR, TIMELIMIT, RUNNING_DIR, ENVFILE, ANAENVFILE, LOG_DIR, RANDBGTAG, PROJECT_ID )



                if BATCHRUN == 1 and BATCHSYS.upper() == "SWIF":
                        print( "All Jobs created.  Please call \"swif run "+WORKFLOW+"\" to run")
                elif BATCHRUN == 2 and BATCHSYS.upper()=="SWIF":
                        swifrun = "swif run "+WORKFLOW
                        subprocess.call(swifrun.split(" "))

                if BATCHRUN == 1 and (BATCHSYS.upper() == "SWIF2" or BATCHSYS.upper() == "SWIF2CONT"):
                        print( "All Jobs created.  Please call \"swif2 run "+WORKFLOW+"\" to run")
                elif BATCHRUN == 2 and (BATCHSYS.upper() == "SWIF2" or BATCHSYS.upper() == "SWIF2CONT"):
                        swifrun = "swif2 run "+WORKFLOW
                        subprocess.call(swifrun.split(" "))

        try:
                dbcnx.close()
        except Exception as e:
                print(e)
                pass

        print("ending gluex_MC.py")

def GetRandTrigNums(BGFOLD,RANDBGTAG,BATCHSYS,RUNNUM):
        try:
                print("GETTING RANDOM COUNT")
                if BGFOLD[0:3] != "Ran" and BGFOLD[0:3] != "loc":
                        return -1
                #print BGFOLD
                #print RANDBGTAG
                Style=BGFOLD
                #print BGFOLD[0:3]
                if BGFOLD[0:3] == "loc":
                        Style="loc"

                path_base="/work/osgpool/halld/random_triggers/"



                if Style=="Random":
                        path_base=path_base+RANDBGTAG+"/"
                else:
                        path_base=BGFOLD[4:]

                formattedRUNNUM=""
                for i in range(len(str(RUNNUM)),6):
                        formattedRUNNUM+="0"

                formattedRUNNUM=formattedRUNNUM+str(RUNNUM)
                path_base=path_base+"run"+formattedRUNNUM+"_random.hddm"
                #print(path_base)

                running_hostname=socket.gethostname()
                if running_hostname == "scosg16.jlab.org" or running_hostname == "scosg20.jlab.org" or running_hostname == "scosg2201.jlab.org":
                        #os.system("scp sci-xrootd.jlab.org:/osgpool/halld/"+"/random_triggers/"+RANDBGTAG+"/run"+formattedRUNNUM+"_random.hddm /tmp/")
                        path_base="/tmp/"+RANDBGTAG+"/run"+formattedRUNNUM+"_random.hddm"

                print("final path base:",path_base)
                realpath=os.path.realpath(path_base)
                print("real path:",realpath)


                queryrand="SELECT Num_Events FROM Randoms WHERE Style=\""+Style+"\" && Tag=\""+RANDBGTAG+"\""+" && Run_Number="+str(RUNNUM)#+" && Path=\""+str(realpath)+"\""
                print(queryrand)
                dbcursor.execute(queryrand)
                matches = dbcursor.fetchall()
                #print matches
                if len(matches) == 0:
                        print("Attempting to scan and tag this random trigger file")
                        running_hostname=socket.gethostname()
                        if running_hostname == "scosg16.jlab.org" or running_hostname == "scosg20.jlab.org" or running_hostname == "scosg2201.jlab.org":
                                os.system("mkdir -p /tmp/"+RANDBGTAG)
                                print("scp dtn1902:/work/test-xrootd/gluex/mcwrap"+"/random_triggers/"+RANDBGTAG+"/run"+formattedRUNNUM+"_random.hddm /tmp/"+RANDBGTAG)
                                os.system("scp dtn1902:/work/test-xrootd/gluex/mcwrap"+"/random_triggers/"+RANDBGTAG+"/run"+formattedRUNNUM+"_random.hddm /tmp/"+RANDBGTAG)

                        if not os.path.isfile(realpath):
                                print("can't find file to scan.")
                                return -1

                        Size=os.stat(realpath).st_size
                        Count=CountFile(realpath)
                        #print Count
                        addquery="INSERT INTO Randoms (Style,Tag,Path,Size,Num_Events,Run_Number) VALUES (\""+str(Style)+"\",\""+str(RANDBGTAG)+"\",\""+str(realpath) +"\",\""+str(Size)+"\","+str(Count)+","+str(RUNNUM)+")"
                        #print addquery
                        dbcursor.execute(addquery)
                        dbcnx.commit()
                        print("COUNT: "+str(Count))
                        os.system("rm -f /tmp/"+RANDBGTAG+"/run"+formattedRUNNUM+"_random.hddm")
                        return Count
                elif len(matches) == 1:
                        print("Matched a file!")
                        print(matches[0][0])
                        return matches[0][0]
                else:
                        #print(matches[0])
                        value=matches[0][0]
                        for match in matches:
                                if match[0] != value:
                                        print("AMBIGUOUS!")
                                        return -1

                        return value
        except Exception as e:
                print(e)
                pass


        return -1

def CountFile(file):
        return sum(1 for r in hddm_s.istream(file))

if __name__ == "__main__":
   main(sys.argv[1:])
