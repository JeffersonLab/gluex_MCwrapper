#!/bin/bash -f

#store whoami in a variable

running_user=`whoami`

if [[ -f /osgpool/halld/$running_user/.ALLSTOP ]]; then
    echo "ALL STOP DETECTED"
fi

echo `ps all -u $running_user | grep MCDrone.sh`
echo `ps all -u $running_user | grep MCDrone.sh | grep -v grep | wc -l`

if [[ `ps all -u $running_user | grep MCDrone.sh | grep -v grep | wc -l` == 2 ]]; then
    cd /tmp/ #/volatile/halld/home/tbritton/
    echo "sourcing"
    source /osgpool/halld/$running_user/local_setup.sh
    #echo "path appends"
    #export PATH=/apps/bin:${PATH};
    #export PATH=/site/bin:${PATH};
    echo "running the drone"
    python3 $MCWRAPPER_CENTRAL/Utilities/MCDrone.py
else
    echo "too many running"

fi
