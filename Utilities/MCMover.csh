#!/bin/bash -f                                                                                                                                                                                                      

source /osgpool/halld/tbritton/local_setup.sh

if [[ -f /osgpool/halld/tbritton/.ALLSTOP ]]; then
    echo "ALL STOP DETECTED"
fi

if [[ `ps all -u tbritton | grep MCMover.csh | grep -v grep | wc -l` == 2 ]]; then
    echo "moving"
    input_dir=/osgpool/halld/tbritton/REQUESTEDMC_OUTPUT
    output_dir=/cache/halld/halld-scratch/REQUESTED_MC/
    rsync_command="rsync -ruvt $input_dir/ $output_dir/"
    echo rsync_command = $rsync_command
    status="255"
    while [ "$status" -eq "255" ]
    do
        $rsync_command
        status="$?"
        echo status = $status
        sleep 1
    done
    cd $output_dir
    find . -type f | sort > /tmp/output_files_list.txt
    cd $input_dir
    find . -type f -mmin +120 | sort > /tmp/input_files_list.txt
    comm -12 /tmp/input_files_list.txt /tmp/output_files_list.txt | xargs rm -v
    
else
    echo "too many running"
fi