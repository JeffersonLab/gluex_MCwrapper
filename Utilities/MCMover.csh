#!/bin/bash -f                                                                                                                                                                                                      

source /osgpool/halld/tbritton/local_setup.sh

if [[ -f /osgpool/halld/tbritton/.ALLSTOP ]]; then
    echo "ALL STOP DETECTED"
fi

if [[ `ps all -u tbritton | grep MCMover.csh | grep -v grep | wc -l` == 2 ]]; then

    rsync -ruvt --remove-source-files /osgpool/halld/tbritton/REQUESTEDMC_OUTPUT/ /lustre/expphy/cache/halld/halld-scratch/REQUESTED_MC/

fi
