import os
import signal
import argparse
import shutil

from flask import Flask, render_template, send_file, redirect, request, send_from_directory, url_for, abort
from flask_httpauth import HTTPBasicAuth
from flask_cors import CORS
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.serving import run_simple

from updog.utils.path import is_valid_subpath, is_valid_upload_path, get_parent_directory, process_files
from updog.utils.output import error, info, warn, success
from updog import version as VERSION


def read_write_directory(directory):
    if os.path.exists(directory):
        if os.access(directory, os.W_OK and os.R_OK):
            return directory
        else:
            error('The output is not readable and/or writable')
    else:
        error('The specified directory does not exist')


def parse_arguments():
    parser = argparse.ArgumentParser(prog='updog')
    cwd = os.getcwd()
    parser.add_argument('-d', '--directory', metavar='DIRECTORY', type=read_write_directory, default=cwd,
                        help='Root directory\n'
                             '[Default=.]')
    parser.add_argument('-b', '--bind', metavar='ADDRESS', type=str, default='0.0.0.0',
                        help='Specify alternate bind address [Default=0.0.0.0]')
    parser.add_argument('-p', '--port', type=int, default=9090,
                        help='Port to serve [Default=9090]')
    parser.add_argument('--password', type=str, default='', help='Use a password to access the page. (No username)')
    parser.add_argument('--ssl', action='store_true', help='Use an encrypted connection (ad-hoc certificate)')
    parser.add_argument('--ssl-cert', type=str, default=None, help='Path to SSL certificate file')
    parser.add_argument('--ssl-key', type=str, default=None, help='Path to SSL key file')
    parser.add_argument('--cors', action='store_true', help='Enable CORS (Cross-Origin Resource Sharing)')
    parser.add_argument('--hide-base-path', action='store_true', help='Hide the base directory path (show relative paths only)')
    parser.add_argument('--version', action='version', version='%(prog)s v'+VERSION)

    args = parser.parse_args()

    # Normalize the path
    args.directory = os.path.abspath(args.directory)

    return args


def main():
    args = parse_arguments()

    app = Flask(__name__)
    auth = HTTPBasicAuth()

    if args.cors:
        CORS(app)

    global base_directory
    base_directory = args.directory

    # Deal with Favicon requests
    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(os.path.join(app.root_path, 'static'),
                                   'images/favicon.ico', mimetype='image/vnd.microsoft.icon')

    ############################################
    # File Browsing and Download Functionality #
    ############################################
    @app.route('/', defaults={'path': None})
    @app.route('/<path:path>')
    @auth.login_required
    def home(path):
        # If there is a path parameter and it is valid
        if path and is_valid_subpath(path, base_directory):
            # Take off the trailing '/'
            path = os.path.normpath(path)
            requested_path = os.path.join(base_directory, path)

            # If directory
            if os.path.isdir(requested_path):
                back = get_parent_directory(requested_path, base_directory)
                is_subdirectory = True

            # If file
            elif os.path.isfile(requested_path):

                # Check if the view flag is set
                if request.args.get('view') is None:
                    send_as_attachment = True
                else:
                    send_as_attachment = False

                # Check if file extension
                (filename, extension) = os.path.splitext(requested_path)
                if extension == '':
                    mimetype = 'text/plain'
                else:
                    mimetype = None

                try:
                    return send_file(requested_path, mimetype=mimetype, as_attachment=send_as_attachment)
                except PermissionError:
                    abort(403, 'Read Permission Denied: ' + requested_path)

        else:
            # Root home configuration
            is_subdirectory = False
            requested_path = base_directory
            back = ''

        if os.path.exists(requested_path):
            # Read the files
            try:
                directory_files = process_files(os.scandir(requested_path), base_directory)
            except PermissionError:
                abort(403, 'Read Permission Denied: ' + requested_path)

            # Hide base directory path if requested (for upload form)
            display_path = requested_path
            if args.hide_base_path:
                display_path = requested_path[len(base_directory):] or '/'

            # Calculate relative path for display
            rel_path = os.path.relpath(requested_path, base_directory)
            if rel_path == '.':
                rel_path = '/'
            else:
                rel_path = '/' + rel_path.replace(os.sep, '/')

            # Calculate disk usage
            try:
                disk = shutil.disk_usage(base_directory)
                disk_free = disk.free
                disk_total = disk.total
            except:
                disk_free = disk_total = 0

            return render_template('home.html', files=directory_files, back=back,
                                   directory=display_path, rel_path=rel_path,
                                   disk_free=disk_free, disk_total=disk_total,
                                   is_subdirectory=is_subdirectory, version=VERSION)
        else:
            return redirect('/')

    #############################
    # File Upload Functionality #
    #############################
    @app.route('/upload', methods=['POST'])
    @auth.login_required
    def upload():
        if request.method == 'POST':

            # No file part - needs to check before accessing the files['file']
            if 'file' not in request.files:
                return redirect(request.referrer)

            # Handle hidden base path mode
            path = request.form['path']
            if args.hide_base_path:
                path = base_directory + path
            
            # Prevent file upload to paths outside of base directory
            if not is_valid_upload_path(path, base_directory):
                return redirect(request.referrer)

            for file in request.files.getlist('file'):

                # No filename attached
                if file.filename == '':
                    return redirect(request.referrer)

                # Assuming all is good, process and save out the file
                # TODO:
                # - Add support for overwriting
                if file:
                    filename = secure_filename(file.filename)
                    full_path = os.path.join(path, filename)
                    try:
                        file.save(full_path)
                    except PermissionError:
                        abort(403, 'Write Permission Denied: ' + full_path)

            return redirect(request.referrer)

    #############################
    # Create Folder Functionality
    #############################
    @app.route('/api/mkdir', methods=['POST'])
    @auth.login_required
    def api_mkdir():
        if request.method == 'POST':
            if 'path' not in request.form or 'name' not in request.form:
                return redirect(request.referrer)

            path = request.form['path']
            if args.hide_base_path:
                path = base_directory + path

            if not is_valid_upload_path(path, base_directory):
                return redirect(request.referrer)

            folder_name = secure_filename(request.form['name'])
            if not folder_name:
                return redirect(request.referrer)

            new_path = os.path.join(path, folder_name)
            try:
                os.makedirs(new_path, exist_ok=False)
            except FileExistsError:
                pass
            except PermissionError:
                abort(403, 'Permission Denied')

            return redirect(request.referrer)

    #############################
    # Delete Functionality
    #############################
    @app.route('/api/delete', methods=['POST'])
    @auth.login_required
    def api_delete():
        if request.method == 'POST':
            if 'path' not in request.form:
                return redirect(request.referrer)

            rel_path = request.form['path']
            # Frontend sends relative path like '/folder/file.txt'
            rel_path = rel_path.lstrip('/').replace('/', os.sep)
            
            # Always join with base_directory
            path = os.path.join(base_directory, rel_path)

            if not is_valid_subpath(rel_path, base_directory):
                return redirect(request.referrer)

            try:
                if os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
            except PermissionError:
                abort(403, 'Permission Denied')

            return redirect(request.referrer)

    #############################
    # File Preview Functionality
    #############################
    @app.route('/api/preview/<path:file_path>')
    @auth.login_required
    def api_preview(file_path):
        # Validate and get absolute path
        rel_path = file_path.replace('/', os.sep)
        path = os.path.join(base_directory, rel_path)
        
        if not is_valid_subpath(rel_path, base_directory):
            abort(403, 'Access Denied')
        
        if not os.path.isfile(path):
            abort(404, 'File not found')
        
        # Get file info
        file_size = os.path.getsize(path)
        filename = os.path.basename(path)
        ext = os.path.splitext(path)[1].lower()
        
        # Text file extensions for preview/edit
        text_extensions = {'.txt', '.md', '.json', '.jsonl', '.py', '.java', '.js', '.ts', '.html', '.css', '.scss', '.xml', '.yaml', '.yml', '.ini', '.cfg', '.conf', '.sh', '.bat', '.cmd', '.ps1', '.rs', '.go', '.c', '.cpp', '.h', '.hpp', '.cs', '.rb', '.php', '.sql', '.log'}
        
        # Image extensions
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.bmp', '.ico'}
        
        # Audio extensions
        audio_extensions = {'.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac'}
        
        # Video extensions
        video_extensions = {'.mp4', '.webm', '.mov', '.avi', '.mkv'}
        
        if ext in text_extensions:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read()
                return {
                    'type': 'text',
                    'filename': filename,
                    'content': content,
                    'ext': ext
                }
            except UnicodeDecodeError:
                try:
                    with open(path, 'r', encoding='latin-1') as f:
                        content = f.read()
                    return {
                        'type': 'text',
                        'filename': filename,
                        'content': content,
                        'ext': ext
                    }
                except:
                    abort(400, 'Cannot read file as text')
            except PermissionError:
                abort(403, 'Permission Denied')
        
        elif ext in image_extensions:
            return {
                'type': 'image',
                'filename': filename,
                'url': '/' + file_path,
                'ext': ext
            }
        
        elif ext in audio_extensions:
            return {
                'type': 'audio',
                'filename': filename,
                'url': '/' + file_path,
                'ext': ext
            }
        
        elif ext in video_extensions:
            return {
                'type': 'video',
                'filename': filename,
                'url': '/' + file_path,
                'ext': ext
            }
        
        else:
            abort(400, 'File type not supported for preview')

    #############################
    # File Save Functionality
    #############################
    @app.route('/api/save', methods=['POST'])
    @auth.login_required
    def api_save():
        if request.method == 'POST':
            data = request.get_json()
            if not data or 'path' not in data or 'content' not in data:
                return {'success': False, 'error': 'Invalid request'}, 400
            
            rel_path = data['path'].lstrip('/').replace('/', os.sep)
            path = os.path.join(base_directory, rel_path)
            
            if not is_valid_subpath(rel_path, base_directory):
                return {'success': False, 'error': 'Access denied'}, 403
            
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(data['content'])
                return {'success': True}
            except PermissionError:
                return {'success': False, 'error': 'Permission denied'}, 403
            except Exception as e:
                return {'success': False, 'error': str(e)}, 500

    # Password functionality is without username
    users = {
        '': generate_password_hash(args.password)
    }

    @auth.verify_password
    def verify_password(username, password):
        if args.password:
            # Accept any username, only verify password
            return check_password_hash(users.get(''), password)
        else:
            return True

    # Inform user before server goes up
    success('Serving {} on {}:{}...'.format(args.directory, args.bind, args.port))

    def handler(signal, frame):
        print()
        error('Exiting!')
    signal.signal(signal.SIGINT, handler)

    ssl_context = None
    if args.ssl:
        ssl_context = 'adhoc'
    elif args.ssl_cert and args.ssl_key:
        ssl_context = (args.ssl_cert, args.ssl_key)
    elif args.ssl_cert or args.ssl_key:
        error('Both --ssl-cert and --ssl-key must be provided together')

    run_simple(args.bind, int(args.port), app, ssl_context=ssl_context, threaded=True)


if __name__ == '__main__':
    main()
