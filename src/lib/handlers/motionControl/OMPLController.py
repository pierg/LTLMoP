#!/usr/bin/env python

######################################################################
# Software License Agreement (BSD License)
#
#  Copyright (c) 2010, Rice University
#  All rights reserved.
######################################################################
"""
===================================================================
OMPLController.py - Open Motion Planning Library Motion Controller
===================================================================

Uses Open Motion Planning Library developed by Rice University to generate paths.
"""

try:
    from ompl import util as ou
    from ompl import base as ob
    from ompl import geometric as og
except:
    # if the ompl module is not in the PYTHONPATH assume it is installed in a
    # subdirectory of the parent directory called "py-bindings."
    from os.path import basename, abspath, dirname, join
    import sys
    sys.path.insert(0, join(dirname(dirname(abspath(__file__))),'py-bindings'))
    from ompl import util as ou
    from ompl import base as ob
    from ompl import geometric as og
from time import sleep
from math import fabs
from numpy import *
from __is_inside import *
import math
import sys,os
from scipy.linalg import norm
from numpy.matlib import zeros
import time, sys,os
import scipy as Sci
import scipy.linalg
import Polygon, Polygon.IO
import Polygon.Utils as PolyUtils
import Polygon.Shapes as PolyShapes
import matplotlib.pyplot as plt
from math import sqrt, fabs , pi

class motionControlHandler:
    def __init__(self, proj, shared_data,Space_Dimension,robot_type,max_angle_goal,max_angle_overlap,plotting):
        """
        Space_Dimension(string): dimension of the space operating in. Enter 2 for 2D and 3 for 3D (default=2)
        robot_type (int): Which robot is used for execution. Nao is 1, ROS is 2, ODE is 3, Pioneer is 4(default=3)
        max_angle_goal (float): The biggest difference in angle between the new node and the goal point that is acceptable. If it is bigger than the max_angle, the new node will not be connected to the goal point. The value should be within 0 to 6.28 = 2*pi. Default set to 6.28 = 2*pi (default=6.28)
        max_angle_overlap (float): difference in angle allowed for two nodes overlapping each other. If you don't want any node overlapping with each other, put in 2*pi = 6.28. Default set to 1.57 = pi/2 (default=1.57)
        plotting (int): Enable plotting is 1 and disable plotting is 0 (default=1)
        """
        
        #Parameters
        self.system_print = True
        self.currentRegionPoly  = None                  # polygon of the current region
        self.nextRegionPoly     = None                  # polygon of the next region
        self.map                = {}                    # dictionary of polygons of different regions
        self.all                = Polygon.Polygon()     # polygon of the boundary
        self.OMPLpath = None
        
        # Get references to handlers we'll need to communicate with
        self.drive_handler = proj.h_instance['drive']
        self.pose_handler = proj.h_instance['pose']
    
        # Get information about regions
        self.proj              = proj
        self.coordmap_map2lab  = proj.coordmap_map2lab
        self.coordmap_lab2map  = proj.coordmap_lab2map
        self.last_warning      = 0
        self.previous_next_reg = None
        
        # Information about the spoce dimension
        if Space_Dimension not in [2,3]:
            self.Space_Dimension = 2
        
        # Information about the robot (default set to ODE)
        if robot_type not in [1,2,3,4]:
            robot_type = 3
        self.system = robot_type
        
        # Information about whether plotting is enabled.
        if plotting >= 1:
            self.plotting          = True
        else:
            self.plotting          = False            
            
        # Operate_system (int): Which operating system is used for execution.
        # Ubuntu and Mac is 1, Windows is 2
        if sys.platform in ['win32', 'cygwin']:
            self.operate_system = 2
        else:
            self.operate_system = 1   
                     
        if self.system_print == True:
            print "The operate_system is "+ str(self.operate_system)
        
        # Generate polygon for regions in the map
        for region in self.proj.rfi.regions:
            self.map[region.name] = self.createRegionPolygon(region)
            for n in range(len(region.holeList)): # no of holes
                self.map[region.name] -= self.createRegionPolygon(region,n)

        # Generate the boundary polygon 
        for regionName,regionPoly in self.map.iteritems():
            self.all += regionPoly
        
        # Specify the size of the robot 
        # 1: Nao ; 2: ROS; 3: 0DE; 4: Pioneer
        #  self.radius: radius of the robot (m)
        if  self.system == 1:
            self.radius = 0.15*1.2
        elif self.system == 2:
            self.ROSInitHandler = shared_data['ROS_INIT_HANDLER']
            self.radius = self.ROSInitHandler.robotPhysicalWidth/2
        elif self.system == 3:
            self.radius = 5
        elif self.system == 4:
            self.radius = 0.15

    def gotoRegion(self, current_reg, next_reg, last=False):
        """
        If ``last`` is True, we will move to the center of the destination region.
        Returns ``True`` if we've reached the destination region.
        """
        # Find our current configuration
        pose = self.pose_handler.getPose()
        
        if self.plotting == True:
            if not plt.isinteractive():
                plt.ion()
            plt.hold(True)
            if self.operate_system == 1:
                plt.plot(pose[0],pose[1],'ko') 
                plt.figure(1).canvas.draw()
                    
        if current_reg == next_reg and not last:
            # No need to move!
            self.drive_handler.setVelocity(0, 0)  # So let's stop
            return True

        # Check if Vicon has cut out
        # TODO: this should probably go in posehandler?
        if math.isnan(pose[2]):
            print "WARNING: No Vicon data! Pausing."
            self.drive_handler.setVelocity(0, 0)  # So let's stop
            time.sleep(1)
            return False

        ###This part will be run when the robot goes to a new region, otherwise, the original tree will be used.
        if not self.previous_next_reg == next_reg:
        
            # plotting current pose and the map
            if self.operate_system == 1 and self.plotting == True:
                plt.cla()
                self.plotMap(self.map) 
                plt.plot(pose[0],pose[1],'ko') 

            # Entered a new region. New tree should be formed.
            self.nextRegionPoly    = self.map[self.proj.rfi.regions[next_reg].name]
            self.currentRegionPoly = self.map[self.proj.rfi.regions[current_reg].name]
            self.nextAndcurrentRegionPoly = self.nextRegionPoly+self.currentRegionPoly
            
            if self.system_print == True:
                print "next Region is " + str(self.proj.rfi.regions[next_reg].name)
                print "Current Region is " + str(self.proj.rfi.regions[current_reg].name)

            #set to zero velocity before tree is generated
            self.drive_handler.setVelocity(0, 0)   
            if last:
                transFace = None
            else:
                # Determine the mid points on the faces connecting to the next region (one goal point will be picked among all the mid points later in buildTree)
                transFace   = None
                q_gBundle   = [[],[]] # list of goal points (midpoints of transition faces)
                for i in range(len(self.proj.rfi.transitions[current_reg][next_reg])):
                    pointArray_transface = [x for x in self.proj.rfi.transitions[current_reg][next_reg][i]]
                    transFace = asarray(map(self.coordmap_map2lab,pointArray_transface))
                    coord_x = (transFace[0,0] +transFace[1,0])/2    #mid-point coordinate x
                    coord_y = (transFace[0,1] +transFace[1,1])/2    #mid-point coordinate y
                    goalPoints = hstack((q_gBundle,vstack((coord_x,coord_y))))
                
                if transFace is None:
                    print "ERROR: Unable to find transition face between regions %s and %s.  Please check the decomposition (try viewing projectname_decomposed.regions in RegionEditor or a text editor)." % (self.proj.rfi.regions[current_reg].name, self.proj.rfi.regions[next_reg].name)
                    
            self.OMPLpath = self.plan(goalPoints,0) 
            self.currentState = 1
            print "Going to generate velocity"
            #print OMPLpath
                
            
        # Run algorithm to find a velocity vector (global frame) to take the robot to the next region
        self.Velocity = self.getVelocity([pose[0], pose[1]], self.OMPLpath)
        self.previous_next_reg = next_reg

        # Pass this desired velocity on to the drive handler
        self.drive_handler.setVelocity(self.Velocity[0,0], self.Velocity[1,0], pose[2])
        RobotPoly = Polygon.Shapes.Circle(self.radius,(pose[0],pose[1]))
        
        # check if robot is inside the current region
        departed = not self.currentRegionPoly.overlaps(RobotPoly)
        arrived  = self.nextRegionPoly.covers(RobotPoly)

        if departed and (not arrived) and (time.time()-self.last_warning) > 0.5:
            # Figure out what region we think we stumbled into
            for r in self.proj.rfi.regions:
                pointArray = [self.coordmap_map2lab(x) for x in r.getPoints()]
                vertices = mat(pointArray).T

                if is_inside([pose[0], pose[1]], vertices):
                    print "I think I'm in " + r.name
                    print pose
                    break
            self.last_warning = time.time()

        #print "arrived:"+str(arrived)
        return arrived
            
    def getVelocity(self,p, OMPLpath, last=False):
        """
        This function calculates the velocity for the robot with RRT.
        The inputs are (given in order):
            p        = the current x-y position of the robot
            OMPLpath = path information of the planner
            last = True, if the current region is the last region
                 = False, if the current region is NOT the last region
        """

        pose     = mat(p).T
        
        #print(ss.getSolutionPath().getStates())
        #print(ss.getSolutionPath().getState(0))[0]
        #print(ss.getSolutionPath().getState(0))[1]
        #print(ss.getSolutionPath().getStateCount())
        """
        if self.system_print == True:
            print (OMPLpath.getSolutionPath().getState(self.currentState))[0]   # x-coordinate of the current state
        """
        
        #dis_cur = distance between current position and the next point
        dis_cur  = vstack(((OMPLpath.getSolutionPath().getState(self.currentState))[0],(OMPLpath.getSolutionPath().getState(self.currentState))[1]))- pose

        if norm(dis_cur) < 1.5*self.radius:         # go to next point
            if not self.currentState == OMPLpath.getSolutionPath().getStateCount():
                self.currentState = self.currentState + 1
                dis_cur  = vstack(((OMPLpath.getSolutionPath().getState(self.currentState))[0],(OMPLpath.getSolutionPath().getState(self.currentState))[1]))- pose
        
        Vel = zeros([2,1])
        Vel[0:2,0] = dis_cur/norm(dis_cur)*0.5                    #TUNE THE SPEED LATER
        return Vel
                       
    
    def createRegionPolygon(self,region,hole = None):
        """
        This function takes in the region points and make it a Polygon.
        """
        if hole == None:
            pointArray = [x for x in region.getPoints()]
        else:
            pointArray = [x for x in region.getPoints(hole_id = hole)]
        pointArray = map(self.coordmap_map2lab, pointArray)
        regionPoints = [(pt[0],pt[1]) for pt in pointArray]
        formedPolygon= Polygon.Polygon(regionPoints)
        return formedPolygon
                
    def plotMap(self,mappedRegions):
        """
        Plotting regions and obstacles with matplotlib.pyplot

        number: figure number (see on top)
        """

        #if not plt.isinteractive():
        #    plt.ion()
        #plt.hold(True)

        if self.operate_system == 1:
            for regionName,regionPoly in mappedRegions.iteritems():
                self.plotPoly(regionPoly,'k')
            plt.figure(1).canvas.draw()

    def plotPoly(self,c,string,w = 1):
        """
        Plot polygons inside the boundary
        c = polygon to be plotted with matlabplot
        string = string that specify color
        w      = width of the line plotting
        """
        if bool(c):
            for i in range(len(c)):
                #toPlot = Polygon.Polygon(c.contour(i))
                toPlot = Polygon.Polygon(c.contour(i)) & self.all
                if bool(toPlot):
                    for j in range(len(toPlot)):
                        #BoundPolyPoints = asarray(PolyUtils.pointList(toPlot.contour(j)))
                        BoundPolyPoints = asarray(PolyUtils.pointList(Polygon.Polygon(toPlot.contour(j))))
                        if self.operate_system == 2:
                            self.ax.plot(BoundPolyPoints[:,0],BoundPolyPoints[:,1],string,linewidth=w)
                            self.ax.plot([BoundPolyPoints[-1,0],BoundPolyPoints[0,0]],[BoundPolyPoints[-1,1],BoundPolyPoints[0,1]],string,linewidth=w)                            
                        else:
                            plt.plot(BoundPolyPoints[:,0],BoundPolyPoints[:,1],string,linewidth=w)
                            plt.plot([BoundPolyPoints[-1,0],BoundPolyPoints[0,0]],[BoundPolyPoints[-1,1],BoundPolyPoints[0,1]],string,linewidth=w)
                            plt.figure(1).canvas.draw()
                            
    # return an obstacle-based sampler
    def allocOBValidStateSampler(self,si):
        # we can perform any additional setup / configuration of a sampler here,
        # but there is nothing to tweak in case of the ObstacleBasedValidStateSampler.
        return ob.ObstacleBasedValidStateSampler(si)

    # return an instance of my sampler
    def alloc_MyValidStateSampler(self,si):
        return _MyValidStateSampler(si)

    # This function is needed, even when we can write a sampler like the one
    # above, because we need to check path segments for validity
    def isStateValid(self,state):
        # Let's pretend that the validity check is computationally relatively
        # expensive to emphasize the benefit of explicitly generating valid
        # samples
        sleep(.001)
        print "Running isStateValid"
        # Valid states satisfy the following constraints:
        # inside the current region and the next region
        if self.Space_Dimension == 2:
            return self.nextAndcurrentRegionPoly.covers(PolyShapes.Circle(self.radius,state))
            #return not (fabs(state[0]<.8) and fabs(state[1]<.8) and state[2]>.25 and state[2]<.5)
        else: 
            a = 1   # just making a case for 3D

    def plan(self,goalPoints,samplerIndex):
        """
        goal points: array that contains the coordinates of all the possible goal states
        """
        
        # construct the state space we are planning in
        space = ob.RealVectorStateSpace(self.Space_Dimension)

        # set the bounds
        bounds = ob.RealVectorBounds(self.Space_Dimension)    
        BoundaryMaxMin = self.all.boundingBox()  #0-3:xmin, xmax, ymin and ymax
        bounds.setLow(0,BoundaryMaxMin[0])
        bounds.setHigh(0,BoundaryMaxMin[1])
        bounds.setLow(1,BoundaryMaxMin[2])
        bounds.setHigh(1,BoundaryMaxMin[3])
        space.setBounds(bounds)
        if self.system_print == True:
            print "The bounding box of the boundary is: " + str(self.all.boundingBox() )
            print "The volumd of the bounding box is: " + str(bounds.getVolume())
            
        # define a simple setup class
        ss = og.SimpleSetup(space)

        # set state validity checking for this space
        ss.setStateValidityChecker(ob.StateValidityCheckerFn(self.isStateValid))
        
        # create a start state
        start = ob.State(space)
        pose = self.pose_handler.getPose()
        start[0] = pose[0]
        start[1] = pose[1]

        # create goal states
        """
        print goalPoints
        goalStates = ob.GoalStates(ss.getSpaceInformation())
        for i in range(shape(goalPoints)[1]):
            goal = ob.State(space)
            goal[0] = goalPoints[0,i-1]
            goal[1] = goalPoints[1,i-1]
            goalStates.addState(goal)
        print goalStates
        """
        goalStates = ob.GoalStates(ss.getSpaceInformation())
        NextRegionCenter = self.nextRegionPoly.center()
        # check if the robot is covered by the next reion when it stands in the middle of the region
        if self.nextRegionPoly.covers(PolyShapes.Circle(self.radius,NextRegionCenter)):
            setAsGoal = NextRegionCenter
            if self.system_print == True:
                print "Goal point is the center of the next region"
        else:   # find a random point in the region that the robot can be covered by when it stands there
            goalPointInsideNextRegion = False
            while not goalPointInsideNextRegion:
                sample = self.nextRegionPoly.sample(random.random())
                if self.nextRegionPoly.covers(PolyShapes.Circle(self.radius,sample)):
                    setAsGoal = sample
                    goalPointInsideNextRegion = True
                    if self.system_print == True:
                        print "Goal point is a random point inside the next region: " + str(setAsGoal) 
        goal = ob.State(space)
        goal[0] = setAsGoal[0]
        goal[1] = setAsGoal[1]
        goalStates.addState(goal)   



        # set the start and goal states;
        #ss.setStartAndGoalStates(start, goal)
        ss.setGoal(goalStates)
        ss.setStartState(start)

        # set sampler (optional; the default is uniform sampling)
        si = ss.getSpaceInformation()
        if samplerIndex==1:
            # use obstacle-based sampling
            si.setValidStateSamplerAllocator(ob.ValidStateSamplerAllocator(self.allocOBValidStateSampler))
        elif samplerIndex==2:
            # use my sampler
            si.setValidStateSamplerAllocator(ob.ValidStateSamplerAllocator(self.alloc_MyValidStateSampler))

        # create a planner for the defined space
        planner = og.PRM(si)
        ss.setPlanner(planner)
        

        # attempt to solve the problem within ten seconds of planning time
        solved = ss.solve(10.0)
        if (solved):
            print("Found solution:")
            # print the path to screen
            print(ss.getSolutionPath())
            print(ss.getSolutionPath().getStates())
            print(ss.getSolutionPath().getState(0))
            print(ss.getSolutionPath().getState(0))[0]
            print(ss.getSolutionPath().getState(0))[1]
            print(ss.getSolutionPath().getStateCount())
            PlannerData = ob.PlannerData(si)
            print "get planner data: " + str(ss.getPlannerData(PlannerData))
        else:
            print("No solution found")
        
        if self.plotting == True :
            if self.operate_system == 1:
                plt.suptitle('Map', fontsize=12)
                plt.xlabel('x')
                plt.ylabel('y')
                for i in range(ss.getSolutionPath().getStateCount()-1):
                    #print i
                    #print ((ss.getSolutionPath().getStates())[i][0],(ss.getSolutionPath().getStates())[i+1][0])
                    plt.plot(((ss.getSolutionPath().getStates())[i][0],(ss.getSolutionPath().getStates())[i+1][0]),((ss.getSolutionPath().getStates())[i][1],(ss.getSolutionPath().getStates())[i+1][1]),'b')
                    plt.figure(1).canvas.draw()
            else:
                BoundPolyPoints = asarray(PolyUtils.pointList(regionPoly))
                self.ax.plot(BoundPolyPoints[:,0],BoundPolyPoints[:,1],'k')
                if shape(V)[1] <= 2:
                    self.ax.plot(( V[1,shape(V)[1]-1],q_g[0,0]),( V[2,shape(V)[1]-1],q_g[1,0]),'b')
                else:
                    self.ax.plot(( V[1,E[0,shape(E)[1]-1]], V[1,shape(V)[1]-1],q_g[0,0]),( V[2,E[0,shape(E)[1]-1]], V[2,shape(V)[1]-1],q_g[1,0]),'b')
                self.ax.plot(q_g[0,0],q_g[1,0],'ko')
        #print ss
        return ss
                    
## @cond IGNORE

# This is a problem-specific sampler that automatically generates valid
# states; it doesn't need to call SpaceInformation::isValid. This is an
# example of constrained sampling. If you can explicitly describe the set valid
# states and can draw samples from it, then this is typically much more
# efficient than generating random samples from the entire state space and
# checking for validity.
class _MyValidStateSampler(ob.ValidStateSampler):
    def __init__(self, si):
        super(_MyValidStateSampler, self).__init__(si)
        self.name_ = "my sampler"
        self.rng_ = ou.RNG()

    # Generate a sample in the valid part of the R^2 state space.
    # Valid states satisfy the following constraints:
    # -1<= x,y,z <=1
    # if .25 <= z <= .5, then |x|>.8 and |y|>.8
    def sample(self, state):
        z = self.rng_.uniformReal(-1,1)

        if z>.25 and z<.5:
            x = self.rng_.uniformReal(0,1.8)
            y = self.rng_.uniformReal(0,.2)
            i = self.rng_.uniformInt(0,3)
            if i==0:
                state[0]=x-1
                state[1]=y-1
            elif i==1:
                state[0]=x-.8
                state[1]=y+.8
            elif i==2:
                state[0]=y-1
                state[1]=x-1
            elif i==3:
                state[0]=y+.8
                state[1]=x-.8
        else:
            state[0] = self.rng_.uniformReal(-1,1)
            state[1] = self.rng_.uniformReal(-1,1)
        state[2] = z
        return True





if __name__ == '__main__':
    print("Using default uniform sampler:")
    motionControlHandler.plan(0)
    print("\nUsing obstacle-based sampler:")
    plan(1)
    print("\nUsing my sampler:")
    plan(2)