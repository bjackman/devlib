#pylint: disable=attribute-defined-outside-init
from __future__ import division
import csv
import os
import time
import tempfile
from fcntl import fcntl, F_GETFL, F_SETFL
from string import Template
from subprocess import Popen, PIPE, STDOUT

from devlib import Instrument, CONTINUOUS, MeasurementsCsv
from devlib.exception import HostError
from devlib.utils.misc import which

OUTPUT_CAPTURE_FILE = 'acme-cape.csv'
IIOCAP_CMD_TEMPLATE = Template("""
${iio_capture} -n ${host} -b ${buffer_size} -c -f ${outfile} ${iio_device}
""")

def _read_nonblock(pipe, size=1024):
    fd = pipe.fileno()
    flags = fcntl(fd, F_GETFL)
    flags |= os.O_NONBLOCK
    fcntl(fd, F_SETFL, flags)

    output = ''
    try:
        while True:
            output += pipe.read(size)
    except IOError:
        pass
    return output


class AcmeCapeInstrument(Instrument):

    mode = CONTINUOUS

    def __init__(self, target,
                 iio_capture=which('iio-capture'),
                 host='baylibre-acme.local',
                 iio_devices=['iio:device0'],
                 buffer_size=256):
        super(AcmeCapeInstrument, self).__init__(target)
        self.iio_capture = iio_capture
        self.host = host
        self.iio_devices = iio_devices
        self.buffer_size = buffer_size
        self.sample_rate_hz = 100
        if self.iio_capture is None:
            raise HostError('Missing iio-capture binary')
        self.command = None
        self.processes = None

        for device in self.iio_devices:
            self.add_channel('shunt_{}'.format(device), 'voltage',
                             iio_device=device, iio_column='vshunt mV')
            self.add_channel('bus_{}'.format(device), 'voltage',
                             iio_device=device, iio_column='vbus mV')
            self.add_channel('device_{}'.format(device), 'power',
                             iio_device=device, iio_column='power mW')
            self.add_channel('device_{}'.format(device), 'current',
                             iio_device=device, iio_column='current mA')
            self.add_channel('timestamp_{}'.format(device), 'time_ms',
                             iio_device=device, iio_column='timestamp ms')

    def reset(self, sites=None, kinds=None, channels=None):
        super(AcmeCapeInstrument, self).reset(sites, kinds, channels)

        self.commands = []
        self.raw_data_files = []
        for device in self.iio_devices:
            raw_data_file = tempfile.mkstemp('_{}.csv'.format(device))[1]
            params = dict(
                iio_capture=self.iio_capture,
                host=self.host,
                buffer_size=self.buffer_size,
                iio_device=device,
                outfile=raw_data_file
            )
            self.raw_data_files.append(raw_data_file)
            self.commands.append(IIOCAP_CMD_TEMPLATE.substitute(**params))
            self.logger.debug('ACME cape command: {}'.format(self.command))

    def start(self):
        self.processes = []
        for command in self.commands:
            self.processes.append(Popen(command.split(), stdout=PIPE, stderr=STDOUT))

    def stop(self):
        for process, raw_data_file in zip(self.processes, self.raw_data_files):
            process.terminate()
            timeout_secs = 10
            output = ''
            for _ in xrange(timeout_secs):
                if process.poll() is not None:
                    break
                time.sleep(1)
            else:
                output += _read_nonblock(self.process.stdout)
                self.process.kill()
                self.logger.error('iio-capture did not terminate gracefully')
                if process.poll() is None:
                    msg = 'Could not terminate iio-capture:\n{}'
                    raise HostError(msg.format(output))
            if self.process.returncode != 15: # iio-capture exits with 15 when killed
                output += self.process.stdout.read()
                raise HostError('iio-capture exited with an error ({}), output:\n{}'
                                .format(self.process.returncode, output))
            if not os.path.isfile(raw_data_file):
                raise HostError('Output CSV not generated.')

    def get_data(self, outfile):
        class DeviceReader(object):
            def __init__(self, raw_data_file, columns):
                self._reader = csv.DictReader(open(raw_data_file, 'rb'),
                                              skipinitialspace=True)
                self._current_row = self._reader.next()
                self.columns = columns
                self.finished = False

            @property
            def timestamp(self):
                return self._current_row['timestamp ms']

            @property
            def current_row(self):
                return [self._current_row[c] for c in self.columns]

            def pop_row(self):
                try:
                    self._current_row = self._reader.next()
                except StopIteration:
                    self.finished = True

        active_devices = set(c.iio_device for c in self.active_channels)
        readers = {}
        for device, raw_data_file in zip(self.iio_devices, self.raw_data_files):
            print device
            if device not in active_devices:
                print 'no'
                continue

            if os.stat(raw_data_file).st_size == 0:
                print('"{}" appears to be empty'.format(raw_data_file))
                self.logger.warning('"{}" appears to be empty'.format(raw_data_file))
                continue

            columns = [c.iio_column for c in self.active_channels
                       if c.iio_device == device]
            readers[device] = DeviceReader(raw_data_file, columns)

        print readers.keys()

        with open(outfile, 'wb') as wfh:
            writer = csv.writer(wfh)
            # Write column headers
            writer.writerow([c.label for c in self.active_channels])

            while active_devices:
                row = []
                for channel in self.active_channels:
                    reader = readers[channel.iio_device]
                    row.append(reader.current_row[channel.iio_column])

                writer.writerow(row)

                device_to_pop = min(active_devices, key=lambda d: readers[d].timestamp)
                reader_to_pop = readers[device_to_pop]
                if reader_to_pop.finished:
                    active_devices.remove(reader_to_pop)

        return MeasurementsCsv(outfile, self.active_channels, self.sample_rate_hz)

    def get_raw(self):
        return self.raw_data_files
