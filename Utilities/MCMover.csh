#!/bin/bash -f                                                                                                                                                                                                      

source /osgpool/halld/tbritton/local_setup.sh

if [[ -f /osgpool/halld/tbritton/.ALLSTOP ]]; then
    echo "ALL STOP DETECTED"
fi

if [[ `ps all -u tbritton | grep MCMover.csh | grep -v grep | wc -l` == 2 ]]; then
    echo "moving"
    input_dir=/osgpool/halld/tbritton/REQUESTEDMC_OUTPUT
    output_dir=/cache/halld/halld-scratch/REQUESTED_MC/
    # move slag-like files in the input directory out of the way
    mkdir -p $input_dir/slag
    find $input_dir -maxdepth 1 -type f -exec mv -v {} $input_dir/slag/ \;
    rsync_command="rsync -pruvt $input_dir/ $output_dir/ \
        --exclude $input_dir/slag"
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
    # make list of files in the output directory
    find . -type f | sort > /tmp/output_files_list.txt
    cd $input_dir
    # make list of files in the input directory
    find . -type f -mmin +120 | sort > /tmp/input_files_list.txt
    if [[ `comm -12 /tmp/input_files_list.txt /tmp/output_files_list.txt | wc -l` != 0 ]]; then
        comm -12 /tmp/input_files_list.txt /tmp/output_files_list.txt | xargs rm -v
    fi
    
else
    echo "too many running"
fi
