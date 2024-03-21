# 
import os,sys
from ROOT import TFile,TH1F,TH1D,TH2D,TF1,TLorentzVector,TGenPhaseSpace,TCanvas,gRandom
from array import array
from optparse import OptionParser
from datetime import datetime
import ccdb
from ccdb import Directory, TypeTable, Assignment, ConstantSet

# for directly writing to HDDM
import hddm_s, fileinput, re

# write events directly to HDDM file
def WriteHDDM(hddm_output, particlesP4, particlesGeantID, particlesPDGID):
    
    rea = pev[0].addReactions(1)
    bea = rea[0].addBeams(1)
    bea[0].type = 1
    prop = bea[0].addPropertiesList()
    prop[0].charge = 0
    prop[0].mass = 0.0
    mom = bea[0].addMomenta(1)
    mom[0].E = E
    mom[0].px = 0
    mom[0].py = 0
    mom[0].pz = E

    tar = rea[0].addTargets(1)
    tar[0].type = 14
    mom = tar[0].addMomenta(1)
    mom[0].E = 0.93827231
    mom[0].px = 0
    mom[0].py = 0
    mom[0].pz = 0
    
    vtx = rea[0].addVertices(1)
    ori = vtx[0].addOrigins(1)

    for i, (P4, GeantID, PDGID) in enumerate(zip(particlesP4, particlesGeantID, particlesPDGID)):
        pro = vtx[0].addProducts(1)
        pro[0].decayVertex = 0
        pro[0].id = i + 1
        pro[0].mech = 0 # 0xdeadface
        pro[0].parentid = 0
        pro[0].pdgtype = PDGID
        pro[0].type = GeantID
        mom = pro[0].addMomenta(1)
        mom[0].E = float(P4.E())
        mom[0].px = float(P4.Px())
        mom[0].py = float(P4.Py())
        mom[0].pz = float(P4.Pz())

# compute PS acceptance function with parameters from CCDB
def PSAcceptance(x, par):

    min = par[1]
    max = par[2]

    if x[0] > 2.*min and x[0] < min + max:
        return par[0]*(1-2.*min/x[0])
    elif x[0] >= min + max:
        return par[0]*(2.*max/x[0] - 1)

    return 0.

# get untagged flux from CCDB to seed event generation
def GetFluxCCDB(run, Emin, Emax):

    hflux_ccdb = TH1D("flux", "flux; Photon Beam Energy (GeV); Flux (# photons on target)", 5000, Emin, Emax)
    
    VARIATION = "default"
    CALIBTIME = datetime.now()
    CALIBTIME_USER = CALIBTIME
    CALIBTIME_ENERGY = CALIBTIME

    sqlite_connect_str = os.getenv('CCDB_CONNECTION')
    if sqlite_connect_str == "":
        print("No CCDB_CONNECTION, defaulting to MYSQL connection for flux determination")
        sqlite_connect_str = "mysql://ccdb_user@hallddb.jlab.org/ccdb"

    ccdb_conn = ccdb.AlchemyProvider()                           # this class has all CCDB manipulation functions
    ccdb_conn.connect(sqlite_connect_str)                        # use usual connection string to connect to database
    ccdb_conn.authentication.current_user_name = "root_generator_user"   # to have a name in logs

    photon_endpoint = array('d')
    tagm_tagged_flux = array('d')
    tagm_scaled_energy = array('d')
    tagh_tagged_flux = array('d')
    tagh_scaled_energy = array('d')

    try:
        photon_endpoint_assignment = ccdb_conn.get_assignment("/PHOTON_BEAM/endpoint_energy", run, VARIATION, CALIBTIME_ENERGY)
        photon_endpoint = photon_endpoint_assignment.constant_set.data_table

        tagm_untagged_flux_assignment = ccdb_conn.get_assignment("/PHOTON_BEAM/pair_spectrometer/lumi/tagm/untagged", run, VARIATION, CALIBTIME)
        tagm_untagged_flux = tagm_untagged_flux_assignment.constant_set.data_table
        tagm_scaled_energy_assignment = ccdb_conn.get_assignment("/PHOTON_BEAM/microscope/scaled_energy_range", run, VARIATION, CALIBTIME_ENERGY)
        tagm_scaled_energy_table = tagm_scaled_energy_assignment.constant_set.data_table
        
        tagh_untagged_flux_assignment = ccdb_conn.get_assignment("/PHOTON_BEAM/pair_spectrometer/lumi/tagh/untagged", run, VARIATION, CALIBTIME)
        tagh_untagged_flux = tagh_untagged_flux_assignment.constant_set.data_table
        tagh_scaled_energy_assignment = ccdb_conn.get_assignment("/PHOTON_BEAM/hodoscope/scaled_energy_range", run, VARIATION, CALIBTIME_ENERGY)
        tagh_scaled_energy_table = tagh_scaled_energy_assignment.constant_set.data_table

        PS_accept_assignment = ccdb_conn.get_assignment("/PHOTON_BEAM/pair_spectrometer/lumi/PS_accept", run, VARIATION, CALIBTIME)
        PS_accept = PS_accept_assignment.constant_set.data_table
    except:
        print "Missing flux for run = %d, contact jrsteven@jlab.org" % run
        sys.exit(0)

    # PS acceptance correction
    fPSAcceptance = TF1("PSAcceptance", PSAcceptance, 2.0, 12.0, 3)
    fPSAcceptance.SetParameters(float(PS_accept[0][0]), float(PS_accept[0][1]), float(PS_accept[0][2]))

    # fill histogram
    for tagh_flux, tagh_scaled_energy in zip(tagh_untagged_flux, tagh_scaled_energy_table):
        tagh_energy = float(photon_endpoint[0][0])*(float(tagh_scaled_energy[1])+float(tagh_scaled_energy[2]))/2.
        psAccept = fPSAcceptance.Eval(tagh_energy)
        if psAccept <= 0.0:
            continue

        bin_energy = hflux_ccdb.FindBin(tagh_energy)
        previous_bincontent = hflux_ccdb.GetBinContent(bin_energy)
        current_bincontent = float(tagh_flux[1]) / psAccept
        new_bincontent = previous_bincontent + current_bincontent
        hflux_ccdb.SetBinContent(bin_energy, new_bincontent)

    return hflux_ccdb
    
#################################
# Begin main generator function #
#################################

# Defaults
Nevents = 10000
event = 0;
run = 30496
outfile_name = "gen_output.hddm"
seed = 0
write_ascii = False
diagnostic = False

Emin = 8.2
Emax = 8.8
tmin = 0.0
tmax = 1.5
tslope = 0.0
Mmin = 0.0
Mmax = 1.7

# Define command line options
parser = OptionParser(usage = "phasespace3body.py --nevents Nevents --run RunNumber --out OutputFile")
parser.add_option("-n","--nevents", dest="Nevents", help="Number of events to generate")
parser.add_option("-r","--run", dest="run", help="RunNumber used to generate events")
parser.add_option("-o","--out", dest="out", help="Output HDDM filename")
parser.add_option("-t","--tslope", dest="tslope", help="Exponential slope for -t")
parser.add_option("-s","--seed", dest="seed", help="Random number seed")
parser.add_option("-a","--ascii", dest="write_ascii", help="Write ASCII output file")
parser.add_option("-d","--diag", dest="diag", help="Plot diagnostic histograms")
parser.add_option("--mmax", dest="mmax", help="Maximum mass")
parser.add_option("--mmin", dest="mmin", help="Minimum mass")
parser.add_option("--tmax", dest="tmax", help="Maximum -t")
parser.add_option("--tmin", dest="tmin", help="Minimum -t")

(options, args) = parser.parse_args(sys.argv)

if not options.Nevents or not options.run:
    parser.print_help()
    sys.exit(0)
    
if options.Nevents:
    Nevents = int(options.Nevents)
if options.run:
    run = int(options.run)
if options.out:
    outfile_name = str(options.out)
if options.seed:
    seed = int(options.seed)
if options.write_ascii:
    write_ascii = True
if options.diag:
    diagnostic = True
if options.mmax:
    Mmax = float(options.mmax)
if options.mmin:
    Mmin = float(options.mmin)
if options.tmax:
    tmax = float(options.tmax)
if options.tmin:
    tmin = float(options.tmin)
if options.tslope:
    tslope = float(options.tslope)

# read beam configuration file to set Emin and Emax
try:
    with open("TEMPBEAMCONFIG") as beam_config:
        lines = beam_config.readlines() # list containing lines of file
        for line in lines:
            line = line.strip()
            items = line.split(" ")
            if items[0] == "PhotonBeamLowEnergy": Emin=float(items[1])
            if items[0] == "PhotonBeamHighEnergy": Emax=float(items[1])
except:
    print("Beam configuration file not available, using default Emin=%0.2f and Emax=%0.2f" % (Emin,Emax))

# setup output file
outfile_hddm = hddm_s.ostream(outfile_name)
if write_ascii:
    outfile = open(outfile_name.replace(".hddm",".ascii"),"w");

# set random number seed
gRandom.SetSeed(seed)

# get run-specific flux from CCDB
hflux = GetFluxCCDB(run, Emin, Emax)

# proton target
target = TLorentzVector(0.0, 0.0, 0.0, 0.93827)

# define final state particles
masses = array( 'd', [0.93827, 0.13957, 0.13957] )
particlesP4 = [TLorentzVector(), TLorentzVector(), TLorentzVector()]
particlesGeantID = [14, 8, 9]
particlesPDGID = [2212, 211, -211]
nParticles = len(masses)

# setup phasespace generator
psGen = TGenPhaseSpace()

# setup histograms for monitoring
eGamma = TH1D( "eGamma", " ; E_{#gamma} ", 1000, 0.0, 12.0)
mProtonPip = TH1D( "mProtonPip", " ;M(p#pi^{+}) ", 200, 0.0, 4.0 )
mProtonPim = TH1D( "mProtonPim", " ;M(p#pi^{-}) ", 200, 0.0, 4.0 )
mPiPi = TH1D( "mPiPi", " ;M(#pi#pi) ", 200, 0.0, 4.0 )
tPhiPiPi = TH1D( "tPhiPiPi", " ;t ", 100, 0.0, 10.0 )
dalitz = TH2D( "dalitz", " ; M^{2}(#pi#pi) ; M^{2}(p#pi)", 200, 0, 20, 200, 0, 20)
pVsThetaProton = TH2D( "PVsThetaProton", " ; Momentum (GeV); #theta", 100, 0, 3.14, 100, 0, 10)
pVsThetaPip = TH2D( "PVsThetaPip", " ; Momentum (GeV); #theta", 100, 0, 3.14, 100, 0, 10)
pVsThetaPim = TH2D( "PVsThetaPim", " ; Momentum (GeV); #theta", 100, 0, 3.14, 100, 0, 10)

# optional weighting functions
ftslope = TF1( "tslope", "[0]*exp(-1.0*[1]*x)", 0.0, 1.0 )
fbwrho = TF1( "bsrho", "[0]*TMath::BreitWigner(x,[1],[2])", 0, 1.5)
fbwDelta = TF1( "bsDelta", "[0]*TMath::BreitWigner(x,[1],[2])", 0, 1.5)
ftslope.SetParameters(1,tslope);
fbwrho.SetParameters(0.23,0.77,0.15);
fbwDelta.SetParameters(0.23,1.232,0.15);

# generate events
while event<Nevents:
    
    E = hflux.GetRandom()
    if E<Emin or E > Emax:
        continue
    
    beam = TLorentzVector(0.0, 0.0, E, E)
    w = beam + target;
    psGen.SetDecay(w, nParticles, masses);
    weight = psGen.Generate();
    
    for i in range(nParticles):
        particlesP4[i] = psGen.GetDecay(i)
        if i==0: pProton = particlesP4[i]
        if i==1: pPip = particlesP4[i]
        if i==2: pPim = particlesP4[i]
    
    t = ((pProton + pPip) - target).M2();
    
    # some optional accept/reject cases to weight by BWs or -t slope
    if tslope > 0:
        weight *= ftslope.Eval(abs(t));
        
    # BW weighting optional (add command line switches)
    # weight *= fbwrho.Eval((*pPip+*pPim).M()); # rho
    # weight *= fbwrho.Eval((*pPip+*pProton).M()); # Delta
    
    # accept/reject events by weight
    if gRandom.Uniform() > weight:
        continue
        
    # apply -t cut
    if abs(t) > tmax or abs(t) < tmin:
        continue
        
    # apply M(p pi+) cut
    if (pPip+pProton).M() > Mmax or (pPip+pProton).M() < Mmin:
        continue

    eGamma.Fill( E );
    mProtonPip.Fill( ( pPip + pProton ).M() );
    mProtonPim.Fill( ( pPim + pProton ).M() );
    mPiPi.Fill( ( pPip + pPim ).M() );
    tPhiPiPi.Fill( abs(t) );
    dalitz.Fill( ( pPip + pPim ).M2(), ( pPip + pProton ).M2() );
    pVsThetaProton.Fill( pProton.Theta(), pProton.Vect().Mag() );
    pVsThetaPip.Fill( pPip.Theta(), pPip.Vect().Mag() );
    pVsThetaPim.Fill( pPim.Theta(), pPim.Vect().Mag() );
    
    # write events to HDDM file directly
    event_hddm = hddm_s.HDDM()
    pev = event_hddm.addPhysicsEvents(1)
    pev[0].runNo = int(run)
    pev[0].eventNo = int(event)
    WriteHDDM(pev, particlesP4, particlesGeantID, particlesPDGID)
    outfile_hddm.write(event_hddm)

    if write_ascii:
        # write events in ASCII format for genr8_2_hddm format
        outfile.write("%d %d %d\n" % (run, event, nParticles))
        outfile.write("0 14 %f +1 %f %f %f %f\n" % (pProton.M(), pProton.Px(), pProton.Py(), pProton.Pz(), pProton.E())) 
        outfile.write("0 8 %f +1 %f %f %f %f\n" % (pPip.M(), pPip.Px(), pPip.Py(), pPip.Pz(), pPip.E()))
        outfile.write("0 9 %f -1 %f %f %f %f\n" % (pPim.M(), pPim.Px(), pPim.Py(), pPim.Pz(), pPim.E()))

    if event % 5000 == 0:
        print("generated %d events" % event)
        
    event = event + 1
    # end of event generation loop

# draw monitoring histograms (if requested)
if diagnostic:
    can = TCanvas( "can", "Plot", 1000, 600 )
    can.Divide(3,2)
    
    can.cd(1)
    eGamma.Draw()
    can.cd(2)
    tPhiPiPi.Draw()
    can.cd(3)
    dalitz.Draw("colz")
    can.cd(4)
    mProtonPip.Draw()
    can.cd(5)
    mPiPi.Draw()
    can.cd(6)
    mProtonPim.Draw()
    
    can.Update()
    
    canKin = TCanvas( "canKin", "PlotKin", 1000, 300 )
    canKin.Divide(3,1)
    
    canKin.cd(1)
    pVsThetaProton.Draw("colz")
    canKin.cd(2)
    pVsThetaPip.Draw("colz")
    canKin.cd(3)
    pVsThetaPim.Draw("colz")
    
    canKin.Update()

# close ASCII file (if requested)
if write_ascii:
    outfile.close()
