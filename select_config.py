import os
import subprocess
import logging
import shutil
import tempfile
import glob


class SelectConfig:
    def __init__(self, config):
        self.name = config.get_name().split()[-1]
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.config_dir = os.path.dirname(
            self.printer.start_args['config_file'])
        self.gcode.register_command(
            "SELECT_CONFIG",
            self.cmd_SELECT_CONFIG,
            desc=self.cmd_SELECT_CONFIG_help)
        self.script_path = os.path.expanduser(
            '~/klipper_config_profiles/gen_klipper_config.py')
        self.use_python = config.getboolean('use_python', False)
        self.template_files = config.getlist('templates')
        self.template_dir = os.path.expanduser(config.get('template_dir'))
        self.gcode.register_command('GEN_PROFILE_MENUS',
                                    self.cmd_GEN_PROFILE_MENUS, desc=self.cmd_GEN_PROFILE_MENUS_help)

    cmd_SELECT_CONFIG_help = "Select a klipper configuration"
    cmd_GEN_PROFILE_MENUS_help = "Generate KlipperScreen menus from profiles.cfg"

    def move_old_config(self):
        OLD = os.path.join(self.config_dir, 'OLD')
        if not os.path.exists(OLD):
            os.mkdir(OLD)
        for file in os.listdir(self.config_dir):
            subprocess.call(['cp', os.path.join(self.config_dir, file), OLD])

    def cmd_GEN_PROFILE_MENUS(self, params):
        command = [os.path.expanduser('~/klippy-env/bin/python'), self.script_path,
                   '-o', '{self.config_dir}', '--profile-menus', 'profile_menus.cfg']
        proc = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.stderr:
            self.gcode.respond_info(proc.stderr.decode('utf-8'))
        if proc.stdout:
            self.gcode.respond_info(proc.stdout.decode('utf-8'))
        if proc.returncode == 0:
            self.gcode.respon_info(f'Done.')

    def cmd_SELECT_CONFIG(self, params):
        param_str = params.get_raw_command_parameters()
        globbed_template_paths = []
        for t in self.template_files:
            globbed_template_paths += glob.glob(
                os.path.join(self.template_dir, t))
        out_dir = tempfile.mkdtemp(prefix='klipper_config_profiles')
        os.chmod(out_dir, 0o777)  # TODO needed?
        command = [os.path.expanduser('~/klippy-env/bin/python'), self.script_path,
                   '-o', out_dir, '--templates'] + globbed_template_paths + ['--set'] + param_str.split(' ')
        if self.use_python:
            command.append("--python")
        config_changed = True  # TODO compute config hash and only do thing if needed
        if not config_changed:
            self.gcode.respond_info(
                'Correct config already selected. Doing nothing.')
            return
        # self.gcode.respond_info(' '.join(command))
        proc = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.stderr:
            self.gcode.respond_info(proc.stderr.decode('utf-8'))
        if proc.stdout:
            self.gcode.respond_info(proc.stdout.decode('utf-8'))
        if proc.returncode == 0:
            self.move_old_config()
            for out_file in os.listdir(out_dir):
                shutil.copy(os.path.join(out_dir, out_file), self.config_dir)
            self.gcode.run_script_from_command('RESTART')


def load_config(config):
    return SelectConfig(config)
