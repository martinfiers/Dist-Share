
from functions import *
from version import update_version, compare_versions, apply_minimun_version
import filecmp
import os
import shutil
import git
import pysvn
import subprocess
import pickle
import StringIO
import urllib
import urlparse

FOLDER_SEPARATOR = os.sep
SVN_MARKER = os.path.join(FOLDER_SEPARATOR,'.svn')
DIST_FILE_VERSION = 'v0.3.2'

def netlocsplit(netloc):
    '''split [user[:passwd]@]host[:port] into 4-tuple.'''

    a = netloc.find('@')
    if a == -1:
        user, passwd = None, None
    else:
        userpass, netloc = netloc[:a], netloc[a + 1:]
        c = userpass.find(':')
        if c == -1:
            user, passwd = urllib.unquote(userpass), None
        else:
            user = urllib.unquote(userpass[:c])
            passwd = urllib.unquote(userpass[c + 1:])
    c = netloc.find(':')
    if c == -1:
        host, port = netloc, None
    else:
        host, port = netloc[:c], netloc[c + 1:]
    return host, port, user, passwd


def parseurl(path):
    """
    See https://bitbucket.org/tortoisehg/thg/src/default/tortoisehg/hgqt/sync.py for 
    parsing URL's. I don't know if we can re-use it because it is GPL based.
    """
    if path.startswith('ssh://'):
        scheme = 'ssh'
        p = path[len('ssh://'):]
        user, passwd = None, None
        if p.find('@') != -1:
            user, p = tuple(p.rsplit('@', 1))
            if user.find(':') != -1:
                user, passwd = tuple(user.rsplit(':', 1))
        m = re.match(r'([^:/]+)(:(\d+))?(/(.*))?$', p)
        if m:
            host = m.group(1)
            port = m.group(3)
            folder = m.group(5) or '.'
        else:
            print('Malformed ssh URL', path)
            host, port, folder = '', '', ''
    elif path.startswith(('http://', 'https://', 'svn+https://', 'git://')):
        # work around http://bugs.python.org/issue7904
        if 'svn+https' not in urlparse.uses_netloc:
            urlparse.uses_netloc.append('svn+https')
        if 'git' not in urlparse.uses_netloc:
            urlparse.uses_netloc.append('git')
        snpaqf = urlparse.urlparse(path)
        scheme, netloc, folder, params, query, fragment = snpaqf
        host, port, user, passwd = netlocsplit(netloc)
        if folder.startswith('/'):
            folder = folder[1:]
    else:
        user, host, port, passwd = [''] * 4
        folder = path
        scheme = 'local'
    return user, host, port, folder, passwd, scheme


def reconstruct_url(user, host, port, folder, passwd, scheme):
    parts = [scheme, '://']
    if scheme == 'local':
        return folder
    if scheme == 'ssh' and '@' in host:
        user, host = host.split('@', 1)
    if user:
        parts.append(user)
        if passwd:
            parts.append(':%s'%passwd)
        parts.append('@')
    parts.append(host)
    if port:
        parts.extend([':', port])
    parts.extend(['/', folder])
    return ''.join(parts)
    


class DupllicatedCopyNameException(BaseException):
    """
    This copy name already exists
    """


class NewProjectException(BaseException):
    """
    For some reason it would not possible to create a new project
    """

class RepositoryNotSupported(BaseException):
    """
    The repository type is not yet supported.
    """

class FutureVersionError(BaseException):
    """
    The file that you are loading has a version that is not suported 
    by your Dist Share version. Please update Dist Share
    """


class Copy(object):

    def __init__(self,source_path, name='', license=None):

        self.copy_name = name
        self.items = get_files(source_path)
        self.source_path = source_path
        self.change_profile = {}
        self.avoided_files = []
        self.license = license
        self.files_to_delete = []
        self.removed_files = []
        self.initialized = False
        self.git_username = ''
        self.git_useremail = ''
        self.remote_url = ''
        self.linked_file_license = False
        self.linked_file_license_path = ''
        self.post_update_script = None

    def unavoid_file(self, full_filename):
        files_to_unavoid = []
        for item in self.avoided_files:
            if item.startswith(full_filename):
                files_to_unavoid.append(item)

        for item in files_to_unavoid:
            self.avoided_files.remove(item)

    def avoid_file(self, full_filename):
        if not full_filename in self.avoided_files:
            self.avoided_files.append(full_filename)
        for item in self.items:
            if item.startswith(full_filename) and item not in self.avoided_files:
                self.avoided_files.append(item)

    def add_change(self, full_filename, new_name):
        change_profile = {full_filename:new_name}
        if full_filename in self.change_profile:
            old_name = self.change_profile[full_filename]
            self.schedule_file_to_delete(full_filename,old_name)
        else:
            self.schedule_file_to_delete(full_filename)
        self.change_profile.update(change_profile)

    def remove_change(self, full_filename):
        if full_filename in self.change_profile:
            old_name = self.change_profile[full_filename]
            self.schedule_file_to_delete(full_filename,old_name)
            self.change_profile.pop(full_filename)

    def schedule_file_to_delete(self,full_filename,old_name=None):
        file_to_delete = self.get_copy_path(full_filename)
        if old_name:
            location,_ = split_path(file_to_delete)
            file_to_delete = os.path.join(location,old_name)
        self.files_to_delete.append(file_to_delete)

    def set_copy_location(self,path):
        self.copy_location = path
        if not self.copy_name:
            self.copy_name = path

    def create_new_copy(self):
        self.create_directories_struct()

        for item in self.items:
            if SVN_MARKER in item:
                continue   
            if item in self.avoided_files:
                continue
            if os.path.isfile(item):
                if item in self.change_profile:
                    copy_name = self.get_new_filename(item)
                else:
                    copy_name = item
                relative_item_path = self.get_relative_path(copy_name)
                copy_target = os.path.join(self.copy_location,relative_item_path)

                shutil.copy2(item,copy_target)
                if self.license:
                    self.apply_license(copy_target)

        self.repo = git.Repo.init(self.copy_location)
        
        if self.git_useremail and self.git_username:
            self.git_config_user()
        
        self.create_placeholder_file(self.copy_location)
        self.remove_empty_folders(self.copy_location)
        self.repo.git.add(self.copy_location)
        self.repo.git.commit(m='First commit of the project %s' % self.copy_name)

        self.repo.git.branch('update_branch')   # create an update branch to use when updating repository
        self.initialized = True

    def remove_empty_folders(self,path):

        if not os.path.isdir(path):
            return

        # remove empty subfolders
        files = os.listdir(path)
        if len(files):
            for f in files:
                fullpath = os.path.join(path, f)
                if os.path.isdir(fullpath):
                    self.remove_empty_folders(fullpath)
    
      # if folder empty, delete it
        files = os.listdir(path)
        if len(files) == 0 and not '.git' in path:
            os.rmdir(path)

    def create_placeholder_file(self,path):
        with open(os.path.join(path,'COPY.info'),'w') as f:
            text = "Your copy named '%s' were created. Fell free to remove this file" % self.copy_name
            f.write(text)

    def git_config_user(self):
        gc = git.config.GitConfigParser(os.path.join(self.copy_location,'.git/config'),read_only=False)
        if not gc.has_section('user'):
            gc.add_section('user')
        gc.set('user','name',self.git_username)
        gc.set('user','email',self.git_useremail)

    def create_directories_struct(self):
        if not os.path.exists(self.copy_location):
            os.makedirs(self.copy_location)
        for item in self.items:

            if SVN_MARKER in item:
                continue
            if os.path.isdir(item) and item not in self.avoided_files:
                if item in self.change_profile:
                    item = self.get_new_filename(item)
                relative_path = self.get_relative_path(item)
                copy_target = os.path.join(self.copy_location,relative_path)

                if not os.path.exists(copy_target):
                    os.makedirs(copy_target)

    def get_relative_path(self, path):
        """ Returns the relative path over the self.source_path
        """
        relative_item_path = path.replace(self.source_path,'',1)
        if relative_item_path.startswith(FOLDER_SEPARATOR):
            relative_item_path = relative_item_path.replace(FOLDER_SEPARATOR,'',1)

        return relative_item_path

    def get_new_filename(self,full_filename):
        if full_filename in self.change_profile:
            path,name = split_path(full_filename)
            new_name = self.change_profile[full_filename]
            return os.path.join(path,new_name)
        else:
            return full_filename

    def update_copy(self, changed_files):
        """ Update copy using svn wrapper.
            It allows the code to scan just through modifyied files
        """
        self.repo.git.checkout('update_branch')
        self.repo.git.merge('master')

        updated_items = get_files(self.source_path)
        removed_items = [item for item in self.items if item not in updated_items]
        self.items = updated_items

        self.removed_files = []
        self.avoided_files.sort(key=lambda x: x.count(FOLDER_SEPARATOR))
        self.avoided_files.reverse()
        for item in self.avoided_files:
            self.remove_file(item)

        for item in self.items:
            if SVN_MARKER in item:
                continue
            if not os.path.exists(self.get_copy_path(item)) and item not in self.avoided_files:
                self.copy_new_file(item)

        for item in changed_files:
            self.update_file(item)

        for item in self.files_to_delete:
            self.remove_renamed_file(item)
        self.files_to_delete = []

        self.removed_files.sort(key=lambda x: x.count(FOLDER_SEPARATOR))
        self.removed_files.reverse()

        for item in self.removed_files:
            try:
                self.repo.git.rm(item)
                self.repo.git.commit(m='updating project %s' % self.copy_name)
            except:
                pass # expected error

        self.remove_empty_folders(self.copy_location)
        self.repo.git.add(self.copy_location)
        try:
            self.repo.git.commit(m='updating project %s' % self.copy_name)
        except git.GitCommandError:
            #expected: none to commit
            pass

        if self.post_update_script:
            os.system(post_update_script)

        self.repo.git.checkout('master')
        self.repo.git.merge('update_branch')
        self.repo.git.add(self.copy_location)

    def push_copy(self,remote):
        if hasattr(self,'repo'):
            remote = self.repo.remote(remote)
            remote.push('master')

    def create_remote(self,name,url):
        self.remote_name = name
        self.remote_url = url
        self.repo.create_remote(name,url)

    def remove_renamed_file(self,file_path):
        """ Remove files that were be renamed
        """
        if os.path.exists(file_path):
            self.removed_files.append(file_path)
            os.remove(file_path)

    def remove_file(self,origin_file_path,remove_from_avoided_files=False):
        """ get the origin file path and remove this file from copy
        """
        filepath = self.get_copy_path(origin_file_path)
        if os.path.exists(filepath):
            self.removed_files.append(filepath)
            if os.path.isfile(filepath):
                os.remove(filepath)
            else:
                shutil.rmtree(filepath)
            try:
                self.repo.git.commit(filepath,m='removing file %s' % filepath)
            except:
                pass # expected error
        if remove_from_avoided_files and origin_file_path in self.avoided_files:
            self.avoided_files.remove(origin_file_path)

    def get_copy_path(self,origin_path):
        """ get the origin file path and return its copy equivalent
        """
        if origin_path in self.change_profile:
            copy_name = self.get_new_filename(origin_path)
        else:
            copy_name = origin_path
        relative_file_path = self.get_relative_path(copy_name)

        if relative_file_path.startswith(FOLDER_SEPARATOR):
            relative_file_path = relative_file_path.replace(FOLDER_SEPARATOR,'',1)

        return os.path.join(self.copy_location,relative_file_path)

    def copy_new_file(self,filename):
        copy_name = self.get_copy_path(filename)
        path,name = split_path(copy_name)
        if os.path.isdir(filename):
            if not os.path.exists(copy_name):
                os.makedirs(copy_name)
        else:
            if not os.path.exists(path):
                os.makedirs(path)
            try:
                shutil.copy2(filename,copy_name)
            except IOError as e:
                sys.stderr.write('Warning: File %s could not be copied. Broke link?\n' % filename)

            if self.license:
                self.apply_license(copy_name)

    def update_file(self,filename):
        """ use it to update a file that already exists!!!
        """
        copy_name = self.get_copy_path(filename)
        if os.path.exists(copy_name):
            os.remove(copy_name)
            shutil.copy2(filename,copy_name)
            if self.license:
                self.apply_license(copy_name)

    def update_license(self):
        for item in self.items:
            if item not in self.avoided_files and os.path.isfile(item):
                self.update_file(item)
                abs_path = os.path.abspath(self.get_copy_path(item))
                self.repo.git.add(abs_path)

        try:
            self.repo.git.commit(m='Updating license')
        except git.GitCommandError as e:
            #Expected error: nothing to commit
            sys.stderr.write('Nothing to commit\n')

    def configure_remote(self,git_username,git_useremail,remote_url):
        if remote_url:
            self.repo.git.remote('rm','origin')
            self.create_remote('origin',remote_url)

        if git_username and git_useremail:
            self.git_username = git_username
            self.git_useremail = git_useremail
            self.git_config_user()

    def apply_license(self,copy_name):
        if self.linked_file_license:
            license = open(self.linked_file_license_path).read()
        else:
            license = self.license
        add_license(copy_name,license)

    def add_linked_file_license(self,file_path):
        self.linked_file_license = True
        self.linked_file_license_path = file_path

    def remove_linked_file_license(self):
        self.linked_file_license = False
        self.linked_file_license_path = ''


class CopiesManager(object):

    def __init__(self,path,name=''):
       if not name:
           _,name = split_path(path)
       self.copies = []
       self.source_path = path
       self.current_copy = None

    def create_copy(self,copy_location,name=''):
        copy = Copy(self.source_path,name=name)
        copy.set_copy_location(copy_location)
        # TODO: here you have to make several tests about the copy location!
        self.copies.append(copy)

    def update_all(self, changes):
        """ this mesthod updtaes ALL projects, apllying changes from source
            project to each copy
        """
        for copy in self.copies:
            copy.update_copy(changes)

    def add_license(self,license):
        self.current_copy.license = license

    def avoid_files(self,files):
        for f in files:
            self.current_copy.avoid_file(f)

    def unavoid_files(self,files):
        for f in files:
            self.current_copy.avoid_file(f)

    def _update_copy(self,changes):
        self.current_copy.update_copy(changes)

    def update_copies(self,changes):
        for copy in self.copies:
            copy.update_copy(changes)

    def rename_file(self,full_filename,new_name):
        self.current_copy.add_change(full_filename,new_name)

    def reset_renamed_file(self,full_filename):
        self.current_copy.remove_change(full_filename)

    def set_current_copy(self,copy_path='',copy_name=''):
        if copy_path:
            for i in self.copies:
                if i.copy_location == copy_path:
                    self.current_copy = i
                    break
            else:
                self.current_copy = None
        elif copy_name:
            for i in self.copies:
                if i.copy_name == copy_name:
                    self.current_copy = i
                    break
            else:
                self.current_project = None

    def forget_repo(self):
        for copy in self.copies:
            copy.repo = None

    def remember_repo(self):
        for copy in self.copies:
            try:
                copy.repo = git.Repo(copy.copy_location)
            except git.InvalidGitRepositoryError:
                #git repository was not created yet
                pass

    def remove_files_from_copy(self,items):
        for copy in self.copies:
            for item in items:
                copy.remove_file(item,remove_from_avoided_files=True)

def checkout_repository(url=None, path=None, repository_type=None, callback_get_login=None):
    """
    
    On svn, callback_get_login can be used to ask credentials. This is supported in pysvn.Client().callback_get_login
    """
    
    if url and repository_type:
        if(repository_type=='svn'):
            self.client = pysvn.Client()
            if callback_get_login:
                self.client.callback_get_login = callback_get_login
            self.client.checkout(url=url,path=path)
                
        elif(repository_type=='mercurial'):
            
            credentials = callback_get_login()
            
            print 'mercurial, with credentials: %s:%s'%(credentials[0], '*****')

            import pyhg
            repo = pyhg.Repo(path)
            user, host, port, folder, passwd, scheme = parseurl(url)
            
            url2 = reconstruct_url(user, host, port, folder, credentials[1], scheme)
            
            repo.hg_clone(url2, path, username=credentials[0], password=credentials[1])
            
            
        else:
            raise RepositoryNotSupported("The checkout for %s is not yet supported."%(repository_type))

def update_local_copy(path):
    """
    Currently supported:
    - svn : svn update
    
    To add:
    - hg  : hg pull / hg update
    """
    process = subprocess.Popen(['svn','update',path],stdout=subprocess.PIPE,stdin=subprocess.PIPE)
    output,errors = process.communicate()
    updated_files = []
    deleted_files = []
    new_files = []
    if not errors:
        output = output.split('\n')
        for item in output:
            if item.startswith('U '):
                candidate = ' '.join(item.split()[1:])
                if os.path.exists(candidate):
                    updated_files.append(candidate)
            elif item.startswith('D'):
                item = ' '.join(item.split()[1:])
                deleted_files.append(item)
            elif item.startswith('A '):
                item = ' '.join(item.split()[1:])
                new_files.append(item)
    else:
        raise Exception('Unknow error when updating local copy: %s' % errors)

    return updated_files,deleted_files,new_files


class Project(object):

    def __init__(self,url=None,repository_type=None,path=None,dumped_project=None,callback_get_login=None):

        self.path = path
        self.url = url
        self.repository_type = repository_type

        if  path and url:
            self.init_new_copy(url,path,callback_get_login)
            self.copies_manager = CopiesManager(self.path)
            self.updated_files = set()
            self.project_items = get_files(self.path)
            self._version = DIST_FILE_VERSION

        elif dumped_project:

            project = pickle.loads(dumped_project)

            try:
                project._version
            except AttributeError:
                # apply_minimun_version(project)
                pass
            #TODO: convert versions!
            # versions_diff = compare_versions(project._version,DIST_FILE_VERSION)
            # if versions_diff == 0:
            #     self._version = project._version
            # elif versions_diff == -1:
            #     project = update_version(project)
            #     self._version = DIST_FILE_VERSION
            # elif versions_diff == 1:
            #     raise FutureVersionError()
            
            self.copies_manager = project.copies_manager
            self.copies_manager.remember_repo()
            self.updated_files = project.updated_files
            self.path = project.path
            self.url = project.url
            self.project_items = project.project_items

        else:
            raise Exception("It wasn not possible to create a new project")

    def init_new_copy(self,url,path,callback_get_login=None):
        if os.path.exists(path):
            if not os.path.isdir(path):
                raise Exception("It wasn not possible to create local repository at %" % path)
        else:
            try:
                os.makedirs(path)
            except OSError:
                raise Exception("It wasn not possible to create local repository at %" % path)

        # At this point, the local_copy folder is created and is ready to checkout
        checkout_repository(url=url, path=path, repository_type=self.repository_type,
                            callback_get_login=callback_get_login)

    def add_new_copy(self,path,name=''):
        for copy in self.copies_manager.copies:
                if name == copy.copy_name:
                    raise DupllicatedCopyNameException()
        self.copies_manager.create_copy(path,name=name)
        if name:
            self.copies_manager.set_current_copy(copy_name=name)
        else:
            self.copies_manager.set_current_copy(copy_path=path)

    def create_current_copy(self):
        if not self.copies_manager.current_copy.initialized:
            self.copies_manager.current_copy.create_new_copy()

    def update_copies(self):
        self.copies_manager.update_copies(self.updated_files)
        self.updated_files = set()

    def update_project(self):
        updated_files,deleted_files,new_files = update_local_copy(self.path)
        self.project_items = get_files(self.path)
        for item in updated_files:
            self.updated_files.add(item)
        for copy in self.copies_manager.copies:
            for item in new_files:
                copy.avoid_file(item)
        deleted_files.sort(key=lambda x : x.count(FOLDER_SEPARATOR))
        deleted_files.reverse()
        self.copies_manager.remove_files_from_copy(deleted_files)
        self.update_log = {'A':new_files,'D':deleted_files,'U':updated_files}

    def avoid_files(self,files):
        self.copies_manager.avoid_files(files)

    def unavoid_files(self,files):
        self.copies_manager.unavoid_files(files)

    def dumps(self):
        self.client = None
        self.copies_manager.forget_repo()
        dumped_project = pickle.dumps(self)
        self.copies_manager.remember_repo()
        return dumped_project

    def create_remote(self,name,url):
        self.copies_manager.current_copy.create_remote(name,url)

    def push_current_copy(self,remote='origin'):
        self.copies_manager.current_copy.push_copy(remote)

    def set_current_copy(self,copy_path='',copy_name=''):
        self.copies_manager.set_current_copy(copy_path,copy_name)

    def config_git_user_email(self,username,email):
        self.copies_manager.current_copy.git_username = username
        self.copies_manager.current_copy.git_useremail = email

    def get_copy_by_name(self,name):
        for copy in self.copies_manager.copies:
            if copy.copy_name == name:
                return copy

        return None

    def clone_copy(self, copy_name, clone_name):
        
        if clone_name in [copy.copy_name for copy in self.copies_manager.copies]:
            raise Exception("Name %s already in use." % copy_name)

        copy = self.get_copy_by_name(copy_name)

        clone_path = copy.copy_location[:copy.copy_location.rindex(copy_name)] + clone_name

        self.add_new_copy(clone_path, clone_name)

        clone = self.copies_manager.current_copy
        clone.avoided_files = copy.avoided_files[::]
        clone.change_profile = copy.change_profile.copy()

        self.create_current_copy()

        return self
