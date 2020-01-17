runnb=(61321 61323 61327 61330 61332 61334 61336 61340 61343 61322 61325 61329 61331 61333 61335 61337 61341 61344)
path=/work/halld/home/ijaegle/PRIMEX-D-pre-production-test-with-new-bash
mkdir -p $path
mkdir -p config
evtnb=10000
wname=primex-d-pre-production-test-with-new-bash
sqlite_dir=/work/halld2/home/ijaegle
sqlite_file=ccdb.sqlite
sqlite_path=${sqlite_dir}/${sqlite_file}
cp /group/halld/www/halldweb/html/dist/${sqlite_file} ${sqlite_path}

for gve in 4; do
    for bkgname in None BeamPhotons; do
	for rnb in "${runnb[@]}"; do
	    for gto in compton_simple primex_eta_he4; do
		name=Geant${gve}_bkg_${bkgname}_runnb_${rnb}_gen_$gto
		outdir=$path/$name
		mkdir -p $outdir
		config=config/MC_$name.config
		sed 's,SQLITE_PATH,'${sqlite_path}',g; s,GVE,'${gve}',g; s,BKGNAME,'${bkgname}',g; s,RNB,'${rnb}',g; s,OUTDIR,'${outdir}',g; s,GTO,'${gto}',g; s,WNAME,'${wname}',g' examples/MC.temp > $config
		echo "./gluex_MC.py $config $rnb $evtnb cleanmcsmear=0 batch=2"
		./gluex_MC.py $config $rnb $evtnb cleanmcsmear=0 batch=2
	    done
	done
    done
done
