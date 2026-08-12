#!/bin/bash -f

rcdb_query=$1
min_run=$2
max_run=$3

source /group/halld/Software/build_scripts/gluex_env_boot_jlab.sh
gxenv $HALLD_VERSIONS/version_7.5.0.xml

cmd=(
  python
  /scigroup/mcwrapper/gluex_MCwrapper/Utilities/rcdb_wrapper.py
  "$rcdb_query"
  "$min_run"
  "$max_run"
)
#printf '%q ' "${cmd[@]}"
#printf '\n'

"${cmd[@]}"
