runnb=(61321)
path_out=/work/halld/home/ijaegle/PRIMEX-D-pre-production-test-with-WHIZARD
mkdir -p $path_out
mkdir -p config
evtnb=10000
wname=qed-gluex-primex
sqlite_dir=/work/halld2/home/ijaegle
sqlite_file=ccdb.sqlite
sqlite_path=${sqlite_dir}/${sqlite_file}
#cp /group/halld/www/halldweb/html/dist/${sqlite_file} ${sqlite_path}

path_in=/volatile/halld/home/ijaegle/qed_whizard
h=1
for process in ae_to_aae; do
    for ffile in `ls $path_in/$process*.root`; do
	fname=$(basename $ffile)
	#echo $fname
	fname=${fname/.root/""}
	#echo $fname
	genfig=config/whizard_$fname.cfg
	sed 's,MYPROCESS,'${process}',g; s,LHEFILE,'${ffile}',g' config_whizard.temp > $genfig
	for gve in 4; do
	    for bkgname in None BeamPhotons; do
		for rnb in "${runnb[@]}"; do
		    for gto in whizard; do
			name=Geant${gve}_bkg_${bkgname}_runnb_${rnb}_gen_${gto}_$fname
			outdir=$path_out/$name
			mkdir -p $outdir
			config=config/MC_${name}.config
			sed 's,SQLITE_PATH,'${sqlite_path}',g; s,GVE,'${gve}',g; s,BKGNAME,'${bkgname}',g; s,RNB,'${rnb}',g; s,OUTDIR,'${outdir}',g; s,GTO,'${gto}',g; s,WNAME,'${wname}',g; s,FILENAME,'${genfig}',g' examples/MC_wo.temp > $config
			echo "./gluex_MC.py $config $rnb $evtnb cleanmcsmear=0 batch=1"
			./gluex_MC.py $config $rnb $evtnb cleanmcsmear=0 batch=1
			h=$(($h+1))
		    done
		done
	    done
	done
    done
done
echo 'h ' $h
