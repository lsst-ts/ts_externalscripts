properties([
    buildDiscarder(
        logRotator(
            artifactDaysToKeepStr: '',
            artifactNumToKeepStr: '',
            daysToKeepStr: '14',
            numToKeepStr: '10',
        )
    ),
    // Make new builds terminate existing builds
    disableConcurrentBuilds(
        abortPrevious: true,
    )
])
pipeline {

    agent {
        // To run on a specific node, e.g. for a specific architecture, add `label '...'`.
        docker {
            alwaysPull true
            image 'lsstts/develop-env:develop'
            args "--entrypoint=''"
        }
    }
    options {
      skipDefaultCheckout()
    }
    environment {
        // Python module name.
        MODULE_NAME = "lsst.ts.mtmount"
        work_branches = "${env.GIT_BRANCH} ${env.CHANGE_BRANCH} develop"
        XML_REPORT_PATH = 'jenkinsReport/report.xml'
    }

    stages {
        stage ('Cloning Repos') {
            steps {
                dir(env.WORKSPACE + '/ci/ts_externalscripts') {
                    checkout scm
                }
                dir(env.WORKSPACE + '/ci/summit_utils') {
                    git branch: 'main', url: 'https://github.com/lsst-sitcom/summit_utils.git'
                }
                dir(env.WORKSPACE + '/ci/cwfs') {
                    git branch: 'master', url: 'https://github.com/lsst-ts/cwfs.git'
                }
                dir(env.WORKSPACE + '/ci/ts_observing_utilities') {
                    git branch: 'develop', url: 'https://github.com/lsst-ts/ts_observing_utilities.git'
                }
            }
        }
        stage ('Setup and update dependencies') {
            steps {
                // When using the docker container, we need to change the WHOME path
                // to WORKSPACE to have the authority to install the packages.
                withEnv(["WHOME=${env.WORKSPACE}"]) {
                    sh """
                        source /home/saluser/.setup_dev.sh

                        for repo in \$(ls /home/saluser/repos/)
                        do
                            cd /home/saluser/repos/\$repo
                            /home/saluser/.checkout_repo.sh ${env.work_branches}
                            git pull
                        done

                        cd ${WHOME}/ci/summit_utils
                        eups declare -r . -t current
                        setup atmospec
                        setup summit_utils -t current
                        scons || echo "summit_utils build failed; continuing..."

                        cd ${WHOME}/ci/ts_observing_utilities
                        eups declare -r . -t current
                        setup ts_observing_utilities -t current
                        scons || echo "ts_observing_utilities build failed; continuing..."

                        # Make IDL files
                        make_idl_files.py --all
                    """
                }
            }
        }
        stage('Run unit tests') {
            steps {
                withEnv(["WHOME=${env.WORKSPACE}"]) {
                    sh """
                        source /home/saluser/.setup_dev.sh || echo "Loading env failed; continuing..."
                        setup ts_observing_utilities -t current
                        setup atmospec -t current
                        setup summit_utils -t current
                        cd ${WHOME}/ci/ts_externalscripts
                        setup -r .
                        pytest --cov-report html --cov=${env.MODULE_NAME} --junitxml=${env.XML_REPORT_PATH}
                    """
                }
            }
        }
    }
    post {
        always {
            // The path of xml needed by JUnit is relative to the workspace.
            junit 'ci/ts_externalscripts/jenkinsReport/*.xml'

            // Publish the HTML report.
            publishHTML (
                target: [
                    allowMissing: false,
                    alwaysLinkToLastBuild: false,
                    keepAll: true,
                    reportDir: 'ci/ts_externalscripts/jenkinsReport',
                    reportFiles: 'index.html',
                    reportName: "Coverage Report"
                ]
            )
        }
        cleanup {
            // Clean up the workspace.
            deleteDir()
        }
    }
}
