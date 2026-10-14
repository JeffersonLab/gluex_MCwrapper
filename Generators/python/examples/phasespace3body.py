"""Generate proton, pi+, and pi- phase-space events with CCDB beam flux."""

import os
import sys
from array import array
from dataclasses import dataclass
from datetime import datetime
from optparse import OptionParser
from typing import Any, Optional, Sequence, TextIO

import ccdb
import hddm_s
from ROOT import TF1, TH1D, TH2D, TCanvas, TGenPhaseSpace, TLorentzVector, gRandom

PARTICLE_MASSES = (0.93827, 0.13957, 0.13957)
PARTICLE_GEANT_IDS = (14, 8, 9)
PARTICLE_PDG_IDS = (2212, 211, -211)


@dataclass
class GeneratorSettings:
    """Command-line settings and beam limits, retaining the existing defaults."""

    event_count: int = 10000
    run_number: int = 30496
    output_path: str = "gen_output.hddm"
    seed: int = 0
    write_ascii: bool = False
    diagnostic: bool = False
    energy_min: float = 8.2
    energy_max: float = 8.8
    transfer_min: float = 0.0
    transfer_max: float = 1.5
    transfer_slope: float = 0.0
    mass_min: float = 0.0
    mass_max: float = 1.7


def write_hddm_event(
    physics_events: Sequence[Any],
    beam_energy: float,
    momenta: Sequence[TLorentzVector],
    geant_ids: Sequence[int],
    pdg_ids: Sequence[int],
) -> None:
    """Populate a physics event using explicit beam energy and particle momenta."""
    reactions = physics_events[0].addReactions(1)
    beams = reactions[0].addBeams(1)
    beams[0].type = 1
    properties = beams[0].addPropertiesList()
    properties[0].charge = 0
    properties[0].mass = 0.0
    momentum = beams[0].addMomenta(1)
    momentum[0].E = beam_energy
    momentum[0].px = 0
    momentum[0].py = 0
    momentum[0].pz = beam_energy

    targets = reactions[0].addTargets(1)
    targets[0].type = 14
    momentum = targets[0].addMomenta(1)
    momentum[0].E = 0.93827231
    momentum[0].px = 0
    momentum[0].py = 0
    momentum[0].pz = 0

    vertices = reactions[0].addVertices(1)
    vertices[0].addOrigins(1)
    for index, (particle, geant_id, pdg_id) in enumerate(
        zip(momenta, geant_ids, pdg_ids)
    ):
        products = vertices[0].addProducts(1)
        products[0].decayVertex = 0
        products[0].id = index + 1
        products[0].mech = 0
        products[0].parentid = 0
        products[0].pdgtype = pdg_id
        products[0].type = geant_id
        momentum = products[0].addMomenta(1)
        momentum[0].E = float(particle.E())
        momentum[0].px = float(particle.Px())
        momentum[0].py = float(particle.Py())
        momentum[0].pz = float(particle.Pz())


def pair_spectrometer_acceptance(
    coordinates: Sequence[float], parameters: Sequence[float]
) -> float:
    """Evaluate the existing pair-spectrometer acceptance used by ROOT's TF1."""
    energy = coordinates[0]
    minimum = parameters[1]
    maximum = parameters[2]
    if energy > 2.0 * minimum and energy < minimum + maximum:
        return parameters[0] * (1 - 2.0 * minimum / energy)
    if energy >= minimum + maximum:
        return parameters[0] * (2.0 * maximum / energy - 1)
    return 0.0


def get_flux_from_ccdb(run_number: int, energy_min: float, energy_max: float) -> TH1D:
    """Read the existing CCDB assignments and correct the TAGH untagged flux."""
    flux = TH1D(
        "flux",
        "flux; Photon Beam Energy (GeV); Flux (# photons on target)",
        5000,
        energy_min,
        energy_max,
    )
    variation = "default"
    calibration_time = datetime.now()
    connection_string = os.getenv("CCDB_CONNECTION")
    if connection_string == "":
        print(
            "No CCDB_CONNECTION, defaulting to MYSQL connection for flux determination"
        )
        connection_string = "mysql://ccdb_user@hallddb.jlab.org/ccdb"
    provider = ccdb.AlchemyProvider()
    provider.connect(connection_string)
    provider.authentication.current_user_name = "root_generator_user"

    try:
        endpoint = provider.get_assignment(
            "/PHOTON_BEAM/endpoint_energy", run_number, variation, calibration_time
        ).constant_set.data_table
        # Keep the TAGM lookups: their absence originally prevented generation too.
        provider.get_assignment(
            "/PHOTON_BEAM/pair_spectrometer/lumi/tagm/untagged",
            run_number,
            variation,
            calibration_time,
        ).constant_set.data_table
        provider.get_assignment(
            "/PHOTON_BEAM/microscope/scaled_energy_range",
            run_number,
            variation,
            calibration_time,
        ).constant_set.data_table
        untagged_flux = provider.get_assignment(
            "/PHOTON_BEAM/pair_spectrometer/lumi/tagh/untagged",
            run_number,
            variation,
            calibration_time,
        ).constant_set.data_table
        scaled_energies = provider.get_assignment(
            "/PHOTON_BEAM/hodoscope/scaled_energy_range",
            run_number,
            variation,
            calibration_time,
        ).constant_set.data_table
        acceptance_parameters = provider.get_assignment(
            "/PHOTON_BEAM/pair_spectrometer/lumi/PS_accept",
            run_number,
            variation,
            calibration_time,
        ).constant_set.data_table
    except BaseException:
        print(f"Missing flux for run = {run_number}, contact jrsteven@jlab.org")
        sys.exit(0)

    acceptance_function = TF1(
        "PSAcceptance", pair_spectrometer_acceptance, 2.0, 12.0, 3
    )
    acceptance_function.SetParameters(
        float(acceptance_parameters[0][0]),
        float(acceptance_parameters[0][1]),
        float(acceptance_parameters[0][2]),
    )
    for tagh_flux, scaled_energy in zip(untagged_flux, scaled_energies):
        energy = (
            float(endpoint[0][0])
            * (float(scaled_energy[1]) + float(scaled_energy[2]))
            / 2.0
        )
        acceptance = acceptance_function.Eval(energy)
        if acceptance <= 0.0:
            continue
        bin_number = flux.FindBin(energy)
        previous_content = flux.GetBinContent(bin_number)
        current_content = float(tagh_flux[1]) / acceptance
        flux.SetBinContent(bin_number, previous_content + current_content)
    return flux


class DiagnosticHistograms:
    """Own the existing monitoring histograms and their fill and drawing order."""

    def __init__(self) -> None:
        self.beam_energy = TH1D("eGamma", " ; E_{#gamma} ", 1000, 0.0, 12.0)
        self.proton_pip_mass = TH1D("mProtonPip", " ;M(p#pi^{+}) ", 200, 0.0, 4.0)
        self.proton_pim_mass = TH1D("mProtonPim", " ;M(p#pi^{-}) ", 200, 0.0, 4.0)
        self.pion_pair_mass = TH1D("mPiPi", " ;M(#pi#pi) ", 200, 0.0, 4.0)
        self.transfer = TH1D("tPhiPiPi", " ;t ", 100, 0.0, 10.0)
        self.dalitz = TH2D(
            "dalitz",
            " ; M^{2}(#pi#pi) ; M^{2}(p#pi)",
            200,
            0,
            20,
            200,
            0,
            20,
        )
        self.proton_momentum = TH2D(
            "PVsThetaProton", " ; Momentum (GeV); #theta", 100, 0, 3.14, 100, 0, 10
        )
        self.pip_momentum = TH2D(
            "PVsThetaPip", " ; Momentum (GeV); #theta", 100, 0, 3.14, 100, 0, 10
        )
        self.pim_momentum = TH2D(
            "PVsThetaPim", " ; Momentum (GeV); #theta", 100, 0, 3.14, 100, 0, 10
        )

    def fill(
        self, energy: float, transfer: float, momenta: Sequence[TLorentzVector]
    ) -> None:
        """Fill the original mass, transfer, Dalitz, and momentum distributions."""
        proton, positive_pion, negative_pion = momenta
        self.beam_energy.Fill(energy)
        self.proton_pip_mass.Fill((positive_pion + proton).M())
        self.proton_pim_mass.Fill((negative_pion + proton).M())
        self.pion_pair_mass.Fill((positive_pion + negative_pion).M())
        self.transfer.Fill(abs(transfer))
        self.dalitz.Fill(
            (positive_pion + negative_pion).M2(), (positive_pion + proton).M2()
        )
        self.proton_momentum.Fill(proton.Theta(), proton.Vect().Mag())
        self.pip_momentum.Fill(positive_pion.Theta(), positive_pion.Vect().Mag())
        self.pim_momentum.Fill(negative_pion.Theta(), negative_pion.Vect().Mag())

    def draw(self) -> None:
        """Draw both diagnostic canvases with the existing layout and ROOT names."""
        self._mass_canvas = TCanvas("can", "Plot", 1000, 600)
        self._mass_canvas.Divide(3, 2)
        for pad, histogram, option in (
            (1, self.beam_energy, ""),
            (2, self.transfer, ""),
            (3, self.dalitz, "colz"),
            (4, self.proton_pip_mass, ""),
            (5, self.pion_pair_mass, ""),
            (6, self.proton_pim_mass, ""),
        ):
            self._mass_canvas.cd(pad)
            if option:
                histogram.Draw(option)
            else:
                histogram.Draw()
        self._mass_canvas.Update()
        self._momentum_canvas = TCanvas("canKin", "PlotKin", 1000, 300)
        self._momentum_canvas.Divide(3, 1)
        for pad, histogram in enumerate(
            (self.proton_momentum, self.pip_momentum, self.pim_momentum), start=1
        ):
            self._momentum_canvas.cd(pad)
            histogram.Draw("colz")
        self._momentum_canvas.Update()


class ThreeBodyGenerator:
    """Generate accepted events and write the existing HDDM and optional ASCII data."""

    def __init__(
        self,
        settings: GeneratorSettings,
        flux: TH1D,
        output_stream: "hddm_s.ostream",
        ascii_output: Optional[TextIO] = None,
    ) -> None:
        self._settings = settings
        self._flux = flux
        self._output_stream = output_stream
        self._ascii_output = ascii_output
        self._target = TLorentzVector(0.0, 0.0, 0.0, 0.93827)
        self._masses = array("d", PARTICLE_MASSES)
        self._momenta = [TLorentzVector() for _ in PARTICLE_MASSES]
        self._phase_space = TGenPhaseSpace()
        self._histograms = DiagnosticHistograms()
        self._transfer_weight = TF1("tslope", "[0]*exp(-1.0*[1]*x)", 0.0, 1.0)
        # Keep the dormant Breit-Wigner functions and their original parameters.
        self._rho_weight = TF1("bsrho", "[0]*TMath::BreitWigner(x,[1],[2])", 0, 1.5)
        self._delta_weight = TF1("bsDelta", "[0]*TMath::BreitWigner(x,[1],[2])", 0, 1.5)
        self._transfer_weight.SetParameters(1, settings.transfer_slope)
        self._rho_weight.SetParameters(0.23, 0.77, 0.15)
        self._delta_weight.SetParameters(0.23, 1.232, 0.15)

    def run(self) -> None:
        """Retain sampling order, event weights, cuts, and zero-based numbering."""
        event_number = 0
        settings = self._settings
        while event_number < settings.event_count:
            energy = self._flux.GetRandom()
            if energy < settings.energy_min or energy > settings.energy_max:
                continue
            beam = TLorentzVector(0.0, 0.0, energy, energy)
            total_momentum = beam + self._target
            self._phase_space.SetDecay(total_momentum, len(self._masses), self._masses)
            weight = self._phase_space.Generate()
            for index in range(len(self._masses)):
                self._momenta[index] = self._phase_space.GetDecay(index)
            proton, positive_pion, _negative_pion = self._momenta
            transfer = ((proton + positive_pion) - self._target).M2()
            if settings.transfer_slope > 0:
                weight *= self._transfer_weight.Eval(abs(transfer))
            if gRandom.Uniform() > weight:
                continue
            if (
                abs(transfer) > settings.transfer_max
                or abs(transfer) < settings.transfer_min
            ):
                continue
            if (positive_pion + proton).M() > settings.mass_max or (
                positive_pion + proton
            ).M() < settings.mass_min:
                continue
            self._histograms.fill(energy, transfer, self._momenta)
            self._write_event(event_number, energy)
            if event_number % 5000 == 0:
                print(f"generated {event_number} events")
            event_number += 1
        if settings.diagnostic:
            self._histograms.draw()

    def _write_event(self, event_number: int, energy: float) -> None:
        event = hddm_s.HDDM()
        physics_events = event.addPhysicsEvents(1)
        physics_events[0].runNo = int(self._settings.run_number)
        physics_events[0].eventNo = int(event_number)
        write_hddm_event(
            physics_events, energy, self._momenta, PARTICLE_GEANT_IDS, PARTICLE_PDG_IDS
        )
        self._output_stream.write(event)
        if self._ascii_output is None:
            return
        self._ascii_output.write(
            f"{self._settings.run_number} {event_number} {len(self._masses)}\n"
        )
        for particle, geant_id, charge in zip(
            self._momenta, PARTICLE_GEANT_IDS, ("+1", "+1", "-1")
        ):
            self._ascii_output.write(
                f"0 {geant_id} {particle.M():f} {charge} "
                f"{particle.Px():f} {particle.Py():f} "
                f"{particle.Pz():f} {particle.E():f}\n"
            )


def _parse_settings(argv: Sequence[str]) -> GeneratorSettings:
    """Parse the existing value-taking options, including --ascii and --diag."""
    parser = OptionParser(
        usage="phasespace3body.py --nevents Nevents --run RunNumber --out OutputFile"
    )
    parser.add_option(
        "-n",
        "--nevents",
        dest="event_count",
        metavar="NEVENTS",
        help="Number of events to generate",
    )
    parser.add_option(
        "-r",
        "--run",
        dest="run_number",
        metavar="RUN",
        help="RunNumber used to generate events",
    )
    parser.add_option(
        "-o", "--out", dest="output_path", metavar="OUT", help="Output HDDM filename"
    )
    parser.add_option(
        "-t",
        "--tslope",
        dest="transfer_slope",
        metavar="TSLOPE",
        help="Exponential slope for -t",
    )
    parser.add_option("-s", "--seed", dest="seed", help="Random number seed")
    parser.add_option(
        "-a", "--ascii", dest="write_ascii", help="Write ASCII output file"
    )
    parser.add_option(
        "-d",
        "--diag",
        dest="diagnostic",
        metavar="DIAG",
        help="Plot diagnostic histograms",
    )
    parser.add_option("--mmax", dest="mass_max", metavar="MMAX", help="Maximum mass")
    parser.add_option("--mmin", dest="mass_min", metavar="MMIN", help="Minimum mass")
    parser.add_option("--tmax", dest="transfer_max", metavar="TMAX", help="Maximum -t")
    parser.add_option("--tmin", dest="transfer_min", metavar="TMIN", help="Minimum -t")
    options, _args = parser.parse_args(list(argv))
    if not options.event_count or not options.run_number:
        parser.print_help()
        sys.exit(0)
    settings = GeneratorSettings()
    if options.event_count:
        settings.event_count = int(options.event_count)
    if options.run_number:
        settings.run_number = int(options.run_number)
    if options.output_path:
        settings.output_path = str(options.output_path)
    if options.seed:
        settings.seed = int(options.seed)
    settings.write_ascii = bool(options.write_ascii)
    settings.diagnostic = bool(options.diagnostic)
    for name in (
        "mass_max",
        "mass_min",
        "transfer_max",
        "transfer_min",
        "transfer_slope",
    ):
        value = getattr(options, name)
        if value:
            setattr(settings, name, float(value))
    return settings


def _read_beam_configuration(settings: GeneratorSettings) -> None:
    """Read TEMPBEAMCONFIG, retaining default or partially read limits on failure."""
    try:
        with open("TEMPBEAMCONFIG") as beam_config:
            for line in beam_config.readlines():
                items = line.strip().split(" ")
                if items[0] == "PhotonBeamLowEnergy":
                    settings.energy_min = float(items[1])
                if items[0] == "PhotonBeamHighEnergy":
                    settings.energy_max = float(items[1])
    except BaseException:
        print(
            "Beam configuration file not available, using default "
            f"Emin={settings.energy_min:0.2f} and Emax={settings.energy_max:0.2f}"
        )


def main(argv: Sequence[str]) -> None:
    """Read settings and flux, generate events, and draw optional diagnostics."""
    settings = _parse_settings(argv)
    _read_beam_configuration(settings)
    output_stream = hddm_s.ostream(settings.output_path)
    ascii_output = (
        open(settings.output_path.replace(".hddm", ".ascii"), "w")
        if settings.write_ascii
        else None
    )
    gRandom.SetSeed(settings.seed)
    flux = get_flux_from_ccdb(
        settings.run_number, settings.energy_min, settings.energy_max
    )
    generator = ThreeBodyGenerator(settings, flux, output_stream, ascii_output)
    generator.run()
    if ascii_output is not None:
        ascii_output.close()


if __name__ == "__main__":
    main(sys.argv[1:])
