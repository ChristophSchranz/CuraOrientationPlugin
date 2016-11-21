# Python 2.7 and 3.5
# Author: Christoph Schranz, Salzburg Research

#import sys
#import random
import math
from time import time, sleep
from collections import Counter

import numpy as np

class Tweak:
    """ The Tweaker is an auto rotate class for 3D objects.

    The critical angle CA is a variable that can be set by the operator as
    it may depend on multiple factors such as material used, printing
     temperature, printing speed, etc.

    Following attributes of the class are supported:
    The tweaked z-axis'.
    Euler coords .v and .phi, where v is orthogonal to both z and z' and phi
     the angle between z and z' in rad.
    The rotational matrix .Matrix, the new mesh is created by multiplying each
     vector with R.
    And the relative unprintability of the tweaked object. If this value is
     greater than 10, a support structure is suggested.
        """
    def __init__(self, content, extended_mode=False, verbose=True, CA=45, def_z=[0,0,1]):
        
        self.extended_mode = extended_mode
        n = -np.array(def_z, dtype=np.float64)
        orientations = [[list(n), 0.0]]
        
        ## Preprocess the input mesh format.
        t_start = time()
        mesh = self.preprocess(content)
        t_pre = time()
        
        ## Calculating initial parameters
        initial_n = -np.array(n, dtype=np.float64)
        bottom, overhang, contour = self.lithograph(mesh, initial_n, CA)
        t_ini = time() 
        
        # The initial alignment gets a bonus of 0.05, to neglect rounding errors
        results = np.array([initial_n, bottom, overhang, contour, 
                self.target_function(bottom, overhang, contour) - 0.05])
          
        ## Searching promising orientations: 
        orientations += self.area_cumulation(mesh, n)
        t_areacum = time()
        if extended_mode:
            dialg_time = time()
            orientations += self.death_star(mesh, 12)
            orientations = self.remove_duplicates(orientations)
            dialg_time = time() - dialg_time
            
        t_ds = time()
        if verbose:
            print("Examine {} orientations:".format(len(orientations)))
            print("  %-32s %-10s%-10s%-10s%-10s " %("Alignment:", 
            "Bottom:", "Overhang:", "Contour:", "Unpr.:"))
        
        
        # Calculate the unprintability for each orientation
        for side in orientations:
            orientation = np.array([float("{:6f}".format(-i)) for i in side[0]])
            mesh = self.project_verteces(mesh, orientation)
            bottom, overhang, contour = self.lithograph(mesh, orientation, CA)
            Unprintability = self.target_function(bottom, overhang, contour)
            results = np.vstack((results, [orientation, bottom,
                            overhang, contour, Unprintability]))                        
            if verbose:
                print("  %-32s %-10s%-10s%-10s%-10s " %(str(orientation), 
                round(bottom, 3), round(overhang,3), round(contour,3), round(Unprintability,3)))
        t_lit = time()               
               
        # Best alignment
        best_alignment = results[np.argmin(results[:, 4])]
            
           
        if verbose:
            print("""
Time-stats of algorithm:
  Preprocessing:    \t{pre:2f} s
  Initial Side:     \t{ini:2f} s
  Area Cumulation:  \t{ac:2f} s
  Death Star:       \t{ds:2f} s
  Lithography Time:  \t{lt:2f} s  
  Total Time:        \t{tot:2f} s
""".format(pre=t_pre-t_start, ini=t_ini-t_pre, ac=t_areacum-t_ini, 
           ds=t_ds-t_areacum, lt=t_lit-t_ds, tot=t_lit-t_start))  
           
        if len(best_alignment) > 0:
            [v, phi, Matrix] = self.euler(best_alignment)
            self.Euler = [[v[0],v[1],v[2]], phi]
            self.Matrix = Matrix
            
            self.Alignment=best_alignment[0]
            self.BottomArea = best_alignment[1]
            self.Overhang = best_alignment[2]
            self.Contour = best_alignment[3]
            self.Unprintability = best_alignment[4]
            
        return None


    def target_function(self, bottom, overhang, contour):
        '''This function returns the uprintability for a given set of bottom area
        overhang area and bottom contour lenght, based on an ordinal scale.'''
        ABSOLUTE = 100             # Some values for scaling the printability
        RELATIVE = 1
        CONTOUR = 1 + 0.5*contour
        Unprintability = (overhang/ABSOLUTE) + ((overhang + 1) / (CONTOUR+bottom) /RELATIVE)
        return Unprintability
        
        
    def preprocess(self, content):
        '''The Mesh format gets preprocessed for a better performance.'''
        mesh = np.array(content, dtype=np.float64)
        
        # prefix area vector, if not already done (e.g. in STL format)
        if len(mesh[0]) == 3:
            row_number = int(len(content)/3)
            mesh = mesh.reshape(row_number,3,3)
            v0=mesh[:,0,:]
            v1=mesh[:,1,:]
            v2=mesh[:,2,:]
            normals = np.cross( np.subtract(v1,v0), np.subtract(v2,v0)).reshape(row_number,1,3)
            mesh = np.hstack((normals,mesh))
        
        face_count = len(mesh)
        
        # calc area size and normalise area vector
        area_size = np.sum(np.abs(mesh[:,0,:])**2, axis=-1)**0.5
        mesh[:,0,:] = mesh[:,0,:]/area_size.reshape(face_count, 1)
        area_size = area_size/2

        # append columns with a_min, area_size
        addendum = np.zeros((face_count, 2, 3))
        addendum[:,0,0] = mesh[:,1,2]
        addendum[:,0,1] = mesh[:,2,2]
        addendum[:,0,2] = mesh[:,3,2]
        
        addendum[:,1,0] = area_size.reshape(face_count)
        addendum[:,1,1] = np.max(mesh[:,1:4,2], axis=1)
        addendum[:,1,2] = np.median(mesh[:,1:4,2], axis=1)
        mesh = np.hstack((mesh, addendum))

        # remove small facets (these are essential for countour calculation)
        if not self.extended_mode:
            mesh = np.array([face for face in mesh if face[5,0] >= 1])
            
        sleep(0)  # Yield, so other threads get a bit of breathing space.
        return mesh


    def project_verteces(self, mesh, orientation):
        '''Returning the "lowest" point vector regarding a vector n for
        each vertex.'''
        mesh[:,4,0] = np.inner(mesh[:,1,:], orientation)
        mesh[:,4,1] = np.inner(mesh[:,2,:], orientation)
        mesh[:,4,2] = np.inner(mesh[:,3,:], orientation)
               
        mesh[:,5,1] = np.max(mesh[:,4,:], axis=1)
        mesh[:,5,2] = np.median(mesh[:,4,:], axis=1)
        sleep(0)  # Yield, so other threads get a bit of breathing space.
        return mesh
        
        
    def lithograph(self, mesh, orientation, CA):
        '''Calculating bottom and overhang area for a mesh regarding 
        the vector n.'''
        overhang = 0
        bottom = 0
        ascent = -np.cos((90-CA)*np.pi/180)
        anti_orient = -np.array(orientation)

        total_min = np.amin(mesh[:,4,:])

        # filter bottom area        
        bottoms = np.array([face for face in mesh
                if face[5,1] < total_min + 0.01])
        if len(bottoms) > 0:
            bottom = np.sum(bottoms[:,5,0]) 
        else: bottom = 0
        
        # filter overhangs
        overhangs = np.array([face for face in mesh 
                    if np.inner(face[0], orientation) < ascent])
        overhangs = np.array([face for face in overhangs
                    if face[5,1] > total_min + 0.01])
        plafonds = np.array([face for face in overhangs
                    if (face[0,:]==anti_orient).all()])
        if len(plafonds) > 0:
            plafond = np.sum(plafonds[:,5,0]) 
        else: plafond = 0
        if len(overhangs) > 0:  
            overhang = np.sum(overhangs[:,5,0]) - 0.2*plafond  
        else: overhang = 0
        
        # filter the total length of the bottom area's contour
        if self.extended_mode:
            contours = np.array([face for face in mesh
            if face[5,2] < total_min + 0.01 < face[5,1] ])
            #print("contour count:", str(len(contours)))
            
            if len(contours) > 0:
                #print(contours[:,4,:])
                con = np.array([np.subtract(face[1 + np.argsort(face[4,:])[0],:],
                                            face[1 + np.argsort(face[4,:])[1],:])
                                            for face in contours])
                contours = np.sum(np.abs(con)**2, axis=-1)**0.5
                contour = np.sum(contours)     
            else: # if no contour facets were found, set it > 0 (div by 0)
                contour = 0.1
        else: # considering the bottom area as square, bottom=a**2 ^ contour=4*a
            contour = 4*np.sqrt(bottom)
        
        sleep(0)  # Yield, so other threads get a bit of breathing space.
        return bottom, overhang, contour


    def area_cumulation(self, mesh, n):
        '''Gathering the most auspicious alignments by cumulating the 
        magnitude of parallel area vectors.'''
        if self.extended_mode: best_n = 8
        else: best_n = 5
        orient = Counter()
        
        align = mesh[:,0,:]
        for index in range(len(mesh)):       # Cumulate areavectors
            orient[tuple(align[index])] += mesh[index, 5, 0]

        top_n = orient.most_common(best_n)
        sleep(0)  # Yield, so other threads get a bit of breathing space.
        return [[list(el[0]), float("{:2f}".format(el[1]))] for el in top_n]
       
       
    def death_star(self, mesh, best_n):
        '''Searching normals or random edges with one vertice'''
        vcount = len(mesh)
        
        # Small files need more calculations
        if vcount < 1000: it = 30
        elif vcount < 2000: it = 15
        elif vcount < 5000: it = 5
        elif vcount < 10000: it = 3
        elif vcount < 20000: it = 2
        else: it = 1     
        
        vertexes = mesh[:vcount,1:4,:]
        v0u1 = vertexes[:,np.random.choice(3, 2, replace=False)]
        v0 = v0u1[:,0,:]
        v1 = v0u1[:,1,:]
        v2 = vertexes[:,np.random.choice(3, 1, replace=False)].reshape(vcount, 3)
        
        lst = list()
        for i in range(it):
            v2 = v2[np.random.choice(vcount, vcount),:]
            normals = np.cross( np.subtract(v2,v0), np.subtract(v1,v0))

            # normalise area vector
            area_size = np.sum(np.abs(normals)**2, axis=-1)**0.5
            normals = np.around(normals/area_size.reshape(vcount,1), decimals=6)
    
            lst += [tuple(face) for face in normals if np.isreal(face[0])]
            sleep(0)  # Yield, so other threads get a bit of breathing space.
        
        orient = Counter(lst)
        top_n = orient.most_common(best_n)
        top_n = list(filter(lambda x: x[1]>2, top_n))
        
        # add antiparallel orientations
        top_n += [[[-v[0][0], -v[0][1], -v[0][2] ], v[1]] 
                                                    for v in top_n]
        return [[list(el[0]), el[1]] for el in top_n]


    def remove_duplicates(self, o):
        '''Removing duplicates in orientation'''
        orientations = list()
        for i in o:
            duplicate = None
            for j in orientations:
                sleep(0)  # Yield, so other threads get a bit of breathing space.
                dif = math.sqrt( (i[0][0]-j[0][0])**2 + (i[0][1]-j[0][1])**2 + (i[0][2]-j[0][2])**2 )
                if dif < 0.001:
                    duplicate = True
                    break
            if duplicate is None:
                orientations.append(i)
        return orientations



    def euler(self, bestside):
        '''Calculating euler rotation parameters and rotation matrix'''
        if (bestside[0] == np.array([0, 0, -1])).all():
            v = [1, 0, 0]
            phi = np.pi
        elif (bestside[0]==np.array([0, 0, 1])).all():
            v = [1,0,0]
            phi = 0
        else:
            phi = float("{:2f}".format(np.pi - np.arccos( -bestside[0][2] )))
            v = [-bestside[0][1] , bestside[0][0], 0]
            v = [i / np.sum(np.abs(v)**2, axis=-1)**0.5 for i in v]
            v = np.array([float("{:2f}".format(i)) for i in v])

        R = [[v[0] * v[0] * (1 - math.cos(phi)) + math.cos(phi),
              v[0] * v[1] * (1 - math.cos(phi)) - v[2] * math.sin(phi),
              v[0] * v[2] * (1 - math.cos(phi)) + v[1] * math.sin(phi)],
             [v[1] * v[0] * (1 - math.cos(phi)) + v[2] * math.sin(phi),
              v[1] * v[1] * (1 - math.cos(phi)) + math.cos(phi),
              v[1] * v[2] * (1 - math.cos(phi)) - v[0] * math.sin(phi)],
             [v[2] * v[0] * (1 - math.cos(phi)) - v[1] * math.sin(phi),
              v[2] * v[1] * (1 - math.cos(phi)) + v[0] * math.sin(phi),
              v[2] * v[2] * (1 - math.cos(phi)) + math.cos(phi)]]
        R = [[float("{:2f}".format(val)) for val in row] for row in R] 
        sleep(0)  # Yield, so other threads get a bit of breathing space.
        return v,phi,R
