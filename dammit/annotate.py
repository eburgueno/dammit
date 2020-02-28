# Copyright (C) 2015-2018 Camille Scott
# All rights reserved.
#
# This software may be modified and distributed under the terms
# of the BSD license.  See the LICENSE file for details.

from collections import OrderedDict
import logging
import os
from os import path
import sys

from shmlast.app import CRBL

from dammit import ui
from dammit import log

logger = logging.getLogger(__name__)





def build_default_pipeline(handler, config, databases):
    '''Register tasks for the default dammit pipeline.

    This is all the main tasks, without lastal uniref90 task.

    Args:
        handler (handler.TaskHandler): The task handler to register on.
        config (dict): Config dictionary, which contains the command
            line arguments and the entries from the config file.
        databases (dict): The dictionary of files from a database
            TaskHandler.

    Returns:
        handler.TaskHandler: The handler passed in.
    '''

    register_stats_task(handler)
    register_busco_task(handler, config, databases)
    register_transdecoder_tasks(handler, config, databases)
    register_rfam_tasks(handler, config, databases)
    register_lastal_tasks(handler, config, databases,
                        include_uniref=False, include_nr=False)
    register_user_db_tasks(handler, config, databases)
    register_annotate_tasks(handler, config, databases)

    return handler


def build_full_pipeline(handler, config, databases):
    '''Register tasks for the full dammit pipeline (with uniref90).

    Args:
        handler (handler.TaskHandler): The task handler to register on.
        config (dict): Config dictionary, which contains the command
            line arguments and the entries from the config file.
        databases (dict): The dictionary of files from a database
            TaskHandler.

    Returns:
        handler.TaskHandler: The handler passed in.
    '''
    register_stats_task(handler)
    register_busco_task(handler, config, databases)
    register_transdecoder_tasks(handler, config, databases)
    register_rfam_tasks(handler, config, databases)
    register_lastal_tasks(handler, config, databases,
                        include_uniref=True, include_nr=False)
    register_user_db_tasks(handler, config, databases)
    register_annotate_tasks(handler, config, databases)

    return handler


def build_nr_pipeline(handler, config, databases):
    '''Register tasks for the full+nr dammit pipeline (with uniref90 AND nr).

    Args:
        handler (handler.TaskHandler): The task handler to register on.
        config (dict): Config dictionary, which contains the command
            line arguments and the entries from the config file.
        databases (dict): The dictionary of files from a database
            TaskHandler.

    Returns:
        handler.TaskHandler: The handler passed in.
    '''
    register_stats_task(handler)
    register_busco_task(handler, config, databases)
    register_transdecoder_tasks(handler, config, databases)
    register_rfam_tasks(handler, config, databases)
    register_lastal_tasks(handler, config, databases,
                        include_uniref=True, include_nr=True)
    register_user_db_tasks(handler, config, databases)
    register_annotate_tasks(handler, config, databases)

    return handler


def register_transdecoder_tasks(handler, config, databases,
                                include_hmmer=True):
    '''Register tasks for TransDecoder. TransDecoder first finds long ORFs with
    `TransDecoder.LongOrfs`, which are output as a FASTA file of protein
    sequences. These sequences can are then used to search against Pfam-A for
    conserved domains, and the coordinates from the resulting matches mapped
    back relative to the original transcripts. `TransDecoder.Predict` the builds
    the final gene models based on the training data provided by
    `TransDecoder.LongOrfs`, optionally using the Pfam-A results to keep
    ORFs which otherwise don't fit the model closely enough. Once again,
    note that a proper dammit config dictionary is required.
    '''

    input_fn = handler.files['transcriptome']
    transdecoder_dir = '{0}.transdecoder_dir'.format(input_fn)

    handler.register_task('TransDecoder.LongOrfs',
                          TransDecoderLongOrfsTask().task(input_fn,
                                                          params=config['transdecoder']['longorfs']),
                          files={'longest_orfs': path.join(transdecoder_dir, 'longest_orfs.pep')})

    pfam_fn = None
    if include_hmmer is True:
        pfam_fn = path.join(transdecoder_dir, 'longest_orfs.pep.x.pfam.tbl')
        task = HMMScanTask().task(handler.files['longest_orfs'],
                                   pfam_fn,
                                   databases['Pfam-A'],
                                   cutoff=config['evalue'],
                                   n_threads=config['n_threads'],
                                   sshloginfile=config['sshloginfile'],
                                   params=config['hmmer']['hmmscan'])
        handler.register_task('hmmscan:Pfam-A', task,
                              files={'longest_orfs_pfam': pfam_fn})

        pfam_csv_fn = '{0}.x.pfam-A.csv'.format(input_fn)
        handler.register_task('hmmscan:Pfam-A:remap',
                              get_remap_hmmer_task(handler.files['longest_orfs_pfam'],
                                                   path.join(transdecoder_dir, 'longest_orfs.gff3'),
                                                   pfam_csv_fn),
                              files={'Pfam-A-csv': pfam_csv_fn})

        pfam_gff3 = '{0}.x.pfam-A.gff3'.format(input_fn)
        handler.register_task('gff3:Pfam-A',
                               get_hmmscan_gff3_task(pfam_csv_fn,
                                                     pfam_gff3,
                                                     'Pfam'),
                               files={'Pfam-A-gff3': pfam_gff3})

    predict_params = config['transdecoder']['predict']
    transdecoder_pep = '{0}.transdecoder.pep'.format(input_fn)
    transdecoder_gff3 = '{0}.transdecoder.gff3'.format(input_fn)
    handler.register_task('TransDecoder.Predict',
                          TransDecoderPredictTask().task(input_fn,
                                                         pfam_filename=pfam_fn,
                                                         params=predict_params),
                          files={'transdecoder-pep': transdecoder_pep,
                                 'transdecoder-gff3': transdecoder_gff3})


def register_rfam_tasks(handler, config, databases):
    '''Registers tasks for Infernal's `cmscan` against Rfam. Rfam is an RNA
    secondary structure database comprising covariance models for many known
    RNAs. This is a relatively slow step. A proper dammit config dictionary is
    required.'''

    input_fn = handler.files['transcriptome']
    output_fn = '{0}.x.rfam.tbl'.format(input_fn)
    handler.register_task('cmscan:Rfam',
                          CMScanTask().task(input_fn,
                                            output_fn,
                                            databases['Rfam'],
                                            cutoff=config['evalue'],
                                            n_threads=config['n_threads'],
                                            sshloginfile=config['sshloginfile'],
                                            params=config['infernal']['cmscan']),
                          files={'Rfam': output_fn})

    rfam_gff3 = '{0}.x.rfam.gff3'.format(input_fn)
    handler.register_task('gff3:Rfam',
                          get_cmscan_gff3_task(output_fn,
                                               rfam_gff3,
                                               'Rfam'),
                          files={'Rfam-gff3': rfam_gff3})


def register_lastal_tasks(handler, config, databases,
                          include_uniref=False, include_nr=False):
    '''Register tasks for `lastal` searches. By default, this will just
    align the transcriptome against OrthoDB; if requested, it will align against
    uniref90 as well, which takes considerably longer.

    Args:
        handler (handler.TaskHandler): The task handler to register on.
        config (dict): Config dictionary, which contains the command
            line arguments and the entries from the config file.
        databases (dict): The dictionary of files from a database
            TaskHandler.
        include_uniref (bool): If True, add tasks for searching uniref90.
    '''

    input_fn = handler.files['transcriptome']
    lastal_cfg = config['last']['lastal']

    dbs = OrderedDict()
    dbs['OrthoDB'] = databases['OrthoDB']
    dbs['sprot'] = databases['sprot']
    if include_uniref is True:
        dbs['uniref90'] = databases['uniref90']
    if include_nr is True:
        dbs['nr'] = databases['nr']

    for name, db in dbs.items():
        output_fn = '{0}.x.{1}.maf'.format(input_fn, name)
        handler.register_task('lastal:{0}'.format(name),
                          add_profile_actions(
                              LastalTask().task(input_fn,
                                              db,
                                              output_fn,
                                              translate=True,
                                              cutoff=config['evalue'],
                                              n_threads=config['n_threads'],
                                              frameshift=lastal_cfg['frameshift'],
                                              pbs=config['sshloginfile'],
                                              params=lastal_cfg['params'])),
                              files={name: output_fn})

        best_fn = '{0}.x.{1}.best.csv'.format(input_fn, name)
        gff3_fn = '{0}.x.{1}.best.gff3'.format(input_fn, name)

        handler.register_task('lastal:best-hits:{0}'.format(name),
                              get_maf_best_hits_task(output_fn,
                                                     best_fn),
                              files={'{0}-best-hits'.format(name): best_fn})
        handler.register_task('gff3:{0}'.format(name),
                              get_maf_gff3_task(best_fn,
                                                gff3_fn,
                                                name),
                              files={'{0}-gff3'.format(name): gff3_fn})


def register_annotate_tasks(handler, config, databases):
    '''Register tasks for aggregating the annotations into one GFF3 file
    and writing out summary descriptions in a new FASTA file.

    Args:
        handler (handler.TaskHandler): The task handler to register on.
        config (dict): Config dictionary, which contains the command
            line arguments and the entries from the config file.
        databases (dict): The dictionary of files from a database
            TaskHandler.
    '''
    input_fn = handler.files['transcriptome']
    gff3_files = [fn for name, fn in handler.files.items() if name.endswith('-gff3')]
    merged_gff3 = '{0}.dammit.gff3'.format(input_fn)
    handler.register_task('gff3:merge-all',
                          get_gff3_merge_task(gff3_files, merged_gff3),
                          files={'merged-gff3': merged_gff3})

    annotated_fn = '{0}.dammit.fasta'.format(input_fn)
    handler.register_task('annotate:fasta',
                          get_annotate_fasta_task(input_fn,
                                                  merged_gff3,
                                                  annotated_fn),
                          files={'annotated-fasta': annotated_fn})


def register_user_db_tasks(handler, config, databases):
    '''Run conditional recipricol best hits LAST (CRBL) against the
    user-supplied databases.
    '''

    if not 'user_databases' in config:
        return

    shmlast_tasks = set()
    input_fn = handler.files['transcriptome']
    for db_path in config['user_databases']:
        db_path = path.abspath(db_path)
        db_basename = path.basename(db_path)

        results_fn = '{0}.x.{1}.crbl.csv'.format(input_fn, db_basename)
        gff3_fn = '{0}.x.{1}.crbl.gff3'.format(input_fn, db_basename)

        crbl = CRBL(input_fn,
                    db_path,
                    results_fn,
                    n_threads=config['n_threads'],
                    cutoff=config['evalue'])

        for task in crbl.tasks():
            if tuple(sorted(task.targets)) in shmlast_tasks:
                continue
            shmlast_tasks.add(tuple(sorted(task.targets)))
            task.name = 'user-database:{0}-shmlast-{1}'.format(db_basename,
                                                               task.name)
            handler.register_task(task.name, add_profile_actions(task))
        handler.register_task('gff3:{0}'.format(results_fn),
                              get_shmlast_gff3_task(results_fn,
                                                    gff3_fn,
                                                    db_basename),
                              files={'{0}-crbl-gff3'.format(db_basename): gff3_fn})
        handler.files['{0}-crbl'.format(db_basename)] = results_fn

