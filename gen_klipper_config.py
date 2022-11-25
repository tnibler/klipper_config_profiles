#!/usr/bin/python3
from jinja2 import Environment, FileSystemLoader, meta, StrictUndefined
import sys
import os
import argparse
from configparser import ConfigParser
import pathlib
import glob

# TODO: implement profile switching from gcode
#   - python extra script to generate configs, swap them out and restart klippy
#   - gcode macro wrapper around that command for flexibility
# TODO: do not switch and restart if we're already in the right profile
# to do that: write a special comment at the top of printer.cfg
# and look for that in the python called from gcode
GCODE_COMMAND = 'SELECT_CONFIG'


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Template processor for Klipper configuration files"
    )
    parser.add_argument(
        '--templates', nargs='+', help='Template files to process.')
    parser.add_argument(
        '--output', '-o', help='Location to write the result configuration files to')
    parser.add_argument('--set', metavar='KEY=VALUE', nargs='+', action='append',
                        help='Specify key value pairs that will be supplied to the user_variables function')
    parser.add_argument(
        '--python', action='store_true', help='Enable python script to be executed during template processing. The script user_variables.py in the same directory as the template files must define a user_variables function.')
    parser.add_argument('--profile-menus', metavar='PROFILES_FILE',
                        help='Generate KlipperScreen menus from profile definition file.')
    parser.add_argument('--profile-macros', metavar='PROFILES_FILE',
                        help='Generate macros from profile definition file.')
    parser.add_argument('--current-config', '-c',
                        help='Current printer.cfg file to copy SAVE_CONFIG section from')
    return parser.parse_args()


def parse_kv_pairs(pairs):
    ret = dict()
    if not pairs:
        return ret
    for l in pairs:
        for pair in l:
            s = pair.split('=')
            value = '='.join(s[1:]) if len(s) > 1 else None
            ret[s[0]] = value
    return ret


def process_template_file(file, env: Environment, user_variables, save_config_block, out_dir):
    filename = os.path.basename(file)
    base_template = env.get_template(os.path.basename(file))
    with open(os.path.join(out_dir, os.path.basename(file)), 'w') as f:
        rendered = base_template.render(user_variables)
        if filename == 'printer.cfg' and save_config_block:
            f.write(remove_save_config_section(rendered) + save_config_block)
        else:
            f.write(rendered)


# https://github.com/Klipper3d/klipper/blob/1b56a63abfffb6a19d1ad9ee3f06a1067642dc7c/klippy/configfile.py#L131
AUTOSAVE_HEADER = """
#*# <---------------------- SAVE_CONFIG ---------------------->
#*# DO NOT EDIT THIS BLOCK OR BELOW. The contents are auto-generated.
#*#
"""


def extract_save_config_section(config):
    header_pos = config.find(AUTOSAVE_HEADER)
    if header_pos < 0:
        return ""
    return config[header_pos:]


def remove_save_config_section(config):
    header_pos = config.find(AUTOSAVE_HEADER)
    if header_pos < 0:
        return config
    return config[:header_pos]


def rewrite_save_config_section(from_file, to_config):
    from_contents = open(from_file).read()
    save_config = extract_save_config_section(from_contents)
    stripped = remove_save_config_section(to_config)
    return stripped + save_config


def get_profile_commands(file):
    parser = ConfigParser(empty_lines_in_values=False)
    # parser.read() just silently fails when the file doesn't exist
    parser.read_file(open(file, 'r'))
    profiles = []
    default_profile = {}
    for profile_name in parser.sections():
        if profile_name.lower() == 'default':
            if default_profile:
                eprint('Error: Default profile section defined multiple times')
                sys.exit(1)
            for key in parser[profile_name]:
                default_profile[key] = parser[profile_name][key]
            profiles.append(('Default', default_profile))
        else:
            p = {}
            for key in parser[profile_name]:
                p[key] = parser[profile_name][key]
            profiles.append((profile_name, p))
    ret = []
    for name, profile in profiles:
        params = []
        if default_profile:
            for key in default_profile:
                params.append((key, profile.get(key, default_profile[key])))
        else:
            for key in profile:
                params.append((key, profile[key]))
        command = f'{GCODE_COMMAND} {" ".join(["=".join(p) for p in params])}'
        ret.append((name, command))
    return ret


def write_klipperscreen_menus(profiles, out_file):
    file_contents = (f'[menu __main profiles]\n'
                     f'name: Profiles\n'
                     f'icon: settings\n\n')
    for name, command in profiles:
        menu = (f'[menu __main profiles profile_{name.replace(" ", "_")}]\n'
                f'name: {name}\n'
                f'icon: settings\n'
                f'method: printer.gcode.script\n'
                f'params: {{"script": "{command}"}}\n\n')
        file_contents += menu
    open(out_file, 'w').write(file_contents)


def write_profile_macros(profiles, out_file):
    file_contents = "# Autogenerated macros to switch between configuration profiles"
    for name, command in profiles:
        file_contents += (f'[gcode_macro PROFILE_{name.replace(" ", "_")}]\n'
                          f'gcode:\n'
                          f'\tM117 Switch to profile {name}\n'
                          f'\t{command}\n\n')
    open(out_file, 'w').write(file_contents)


def main():
    args = parse_args()
    out_dir = args.output.strip()  # TODO needed?

    if args.profile_menus:
        if args.set or args.templates:
            eprint(
                "--profile-menus flag provided, ignoring templates and --set args")
        profile_commands = get_profile_commands(args.profile_menus)
        write_klipperscreen_menus(
            profile_commands, os.path.join(out_dir, "profile_menus.conf"))
    if args.profile_macros:
        if args.set or args.templates:
            eprint(
                "--profile-macros flag provided, ignoring templates and --set args")
        profile_commands = get_profile_commands(args.profile_macros)
        write_profile_macros(
            profile_commands, os.path.join(out_dir, "profile_macros.cfg"))
    if not args.profile_macros and not args.profile_menus:
        user_params = parse_kv_pairs(args.set)
        template_paths = list(set([os.path.abspath(os.path.expanduser(p))
                              for p in args.templates]))
        template_dir = os.path.commonprefix(template_paths)
        print(f'Processing templates relative to {template_dir}')
        # make template_paths relative to template_dir
        template_paths = [os.path.relpath(p, template_dir)
                          for p in template_paths]

        user_variables_file = os.path.join(
            template_dir, "user_variables.py") if args.python else None
        # populate user variables
        bound_user_variables = user_params
        if user_variables_file:
            exec_globals = {}
            exec(open(user_variables_file).read(), exec_globals)
            try:
                bound_user_variables = exec_globals['user_variables'](
                    user_params)
            except NameError:
                eprint(
                    f'Error: No user_variables function defined in {user_variables_file}.')
                sys.exit(1)

        save_config_block = None
        if args.current_config:
            save_config_block = extract_save_config_section(
                open(args.current_config).read())
        # process template files
        for template in template_paths:
            searchpath = os.path.dirname(os.path.join(template_dir, template))
            env = Environment(
                loader=FileSystemLoader(
                    searchpath=searchpath, followlinks=True),
                block_start_string='[%',
                block_end_string='%]',
                variable_start_string='[[',
                variable_end_string=']]',
                autoescape=False,
                undefined=StrictUndefined
            )
            od = os.path.join(
                out_dir, os.path.dirname(template))
            if not os.path.exists(od):
                pathlib.Path(od).mkdir(parents=True)
            process_template_file(
                os.path.basename(template), env, bound_user_variables, save_config_block, od)


if __name__ == '__main__':
    main()
