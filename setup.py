"""
    DistShare - A distribution manager.
    
    
    Dependencies
    ------------
    - gitpython and mercurial: To create new repositories
    
    - TIX: Tk Interface eXtension (http://tix.sourceforge.net/). On debian, use apt-get install tix
    
"""

from setuptools import setup

setup(name='Dist Share',
      version='0.1',
      description='Distributions manager',
      author='Intec Photonics',
      author_email='intec@ugent.be',
      url='',
	    install_requires=['gitpython', 'mercurial'],
      packages=['dist_share'],
      entry_points = {
        'console_scripts': [
            'dist-share = dist_share.app:main',
        ],
      },
     )
