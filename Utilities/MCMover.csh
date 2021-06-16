#!/bin/bash -f                                                                                                                                                                                                      

source /osgpool/halld/tbritton/local_setup.sh

if [[ -f /osgpool/halld/tbritton/.ALLSTOP ]]; then
    echo "ALL STOP DETECTED"
fi

if [[ `ps all -u tbritton | grep MCMover.csh | grep -v grep | wc -l` == 2 ]]; then
    echo "=======================================" >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
    echo `date` >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
    echo "=======================================" >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
    echo "moving" >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
    input_dir=/osgpool/halld/tbritton/REQUESTEDMC_OUTPUT/
    transfer_node=tbritton@dtn1902-ib
    output_dir=/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC/
    # move slag-like files in the input directory out of the way
    mkdir -pv $input_dir/slag
    echo "Finding in $input_dir to move to SLAG" >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
    find $input_dir -maxdepth 2 -mindepth 2 -type f -exec mv -v {} /osgpool/halld/tbritton/SLAG/ \;

    #find me the dirs
    movecount=0
    transArray=()
    while IFS=  read -r -d $'\0'; do
        transArray+=("$REPLY")
    done < <(find $input_dir/ -mindepth 2 -maxdepth 2 -type d -not -name ".*" -print0)
    
    #echo ${transArray[*]} >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
    for dir in ${transArray[@]}
    do
        #echo $dir
        projpath=`echo $dir | awk '{split($0,arr,"REQUESTEDMC_OUTPUT"); print arr[2]}'`
        echo $projpath >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
        echo "mkdir -p $output_dir/$projpath/"
        ssh $transfer_node mkdir -p $output_dir/$projpath/

        dir2=${dir}
        echo chmod -R g+w $dir2
	chmod -R g+w $dir2
        rsync_command="rsync --progress -pruvt $dir/ $transfer_node:$output_dir/$projpath/" #--exclude $input_dir/slag"
        echo $rsync_command >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
        status="255"
        while [ "$status" -eq "255" ]
        do
            echo $rsync_command
	    $rsync_command
            status="$?"
            echo status = $status
            sleep 1
        done
        ((movecount=movecount+1))
        echo $movecount
        #if [[ $movecount > 10000 ]]; then
        #    break
        #fi
    done
    #echo "cd $output_dir" >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
    #cd $output_dir
    # make list of files in the output directory
    echo $transfer_node "cd $output_dir;find . -type f | sort > /tmp/output_files_list.txt; scp /tmp/output_files_list.txt tbritton@scosg16-ib:/tmp/output_files_list.txt"
    ssh $transfer_node "cd $output_dir;find . -type f | sort > /tmp/output_files_list.txt; scp /tmp/output_files_list.txt tbritton@scosg16-ib:/tmp/output_files_list.txt"

    #echo "pwd" $PWD >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
    #find . -type f | sort > /tmp/output_files_list.txt
    echo "cd $input_dir" >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
    cd $input_dir

    echo "moving to delete" >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log 
    echo $PWD >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log 

    if [[ $PWD == *"/lustre19/expphy/cache/halld/gluex_simulations/REQUESTED_MC"* ]]; then
        echo "oh no! did not move to input directory?!"
        exit 1
    fi
    # make list of files in the input directory
    find . -type f -mmin +600 | sort > /tmp/input_files_list.txt
    echo "DELETING" >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
    echo `comm -12 /tmp/input_files_list.txt /tmp/output_files_list.txt` >> /osgpool/halld/tbritton/MCWrapper_Logs/MCWrapperMover.log
    if [[ `comm -12 /tmp/input_files_list.txt /tmp/output_files_list.txt | wc -l` != 0 ]]; then
        comm -12 /tmp/input_files_list.txt /tmp/output_files_list.txt | xargs rm -v
    fi

    #clean empty directories
    #find $input_dir -depth -empty -type d mmin -2880 -exec rmdir {} \;
    
else
    echo "too many running"
fi
