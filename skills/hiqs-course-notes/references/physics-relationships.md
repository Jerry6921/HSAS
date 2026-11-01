# Physics Notes: Quantities, Formula Connections and Solution Paths

Read this guide when authoring or revising physics and physics-based engineering
notes. It implements the relationship requirements in English Course Notes.
Use only the relationships justified by the declared source/model scope; label
teaching additions. These examples illustrate the method, not extra mandatory
syllabus content.

## 1. Plan a topic, then its connected concepts

Choose a topic title such as **Dynamics** and organize its internal headings by
the conceptual progression in the actual course. A possible sequence is motion
description → forces → work and energy → momentum → rotation, with prerequisites
repaired where needed. A course with a different sequence can use a different
outline.

At the topic opening, identify the physical questions and the concepts needed
to answer them. Include a jumpable contents block, then connect adjacent
sections in the prose: what the previous section establishes, which question
remains, and what the next relation adds. At major transitions, link back to the
relevant definition or derivation.

Keep definitions, essential reasoning and conditions visible. Use toggles for
prediction answers or extra practice. Teach the full topic through substantial
sections; use internal generation batches for recovery and authoring convenience.
Do not create a new student-facing page merely because a batch ended.

## 2. Explain each central physical quantity through its relationships

### Establish the quantity's identity before using it

Start with a physical scene, selected system/body/point, observation frame and
model constraints. State which question a new quantity answers and its level of
description: whole-body orientation, a point's motion, an interaction, stored
energy or a component of another quantity. Introduce this classification before
equations whose interpretation depends on it. Similar names and compatible
dimensions are not sufficient evidence that two quantities mean the same thing.

For every directional representation, explain what its arrow means in that
model. A velocity arrow gives instantaneous motion direction; an acceleration
arrow gives velocity-change direction; an angular-velocity axial arrow encodes
rotation axis and sense by the right-hand rule. State the latter's convention
and physical interpretation together: its axial direction does not indicate
translation along that axis. Fix viewing face, axes, positive direction and the
selected point before comparing arrows.

### Identify the type of relationship

Explain the relation's role beside the equation, rather than leaving readers to
infer it from an equals sign. Distinguish identity/equivalent representation,
component decomposition, derivative/rate, geometric conversion, physical law,
conservation and constraint. Reuse the types relevant to the course; a formula
list need not become a separate taxonomy exercise.

| Example under stated conditions | Relationship and interpretation |
|---|---|
| a = at + ac, as vectors | Perpendicular components of one point's linear acceleration in circular motion |
| α = dω/dt, for a fixed axis | Angular acceleration is the rate of change of angular velocity, not another spatial component |
| aθ = rα, for fixed radius about a stationary axis | Geometry connects angular change to a point's signed tangential acceleration |
| Fnet = ma, for constant mass in an inertial frame | A physical law relates net interaction to acceleration; force and acceleration remain different quantities |
| K = ½mv², with v denoting speed in the particle model | Kinetic energy is a scalar state quantity; it retains speed information and loses velocity direction |

### Reveal the classification with a controlled contrast

Before changing geometry or observation frame, hold one scene fixed and vary one
condition. For fixed-axis rotation, view the disc face-on, take +z toward the
observer, select its rightmost point and keep counterclockwise rotation. Compare
increasing, constant and decreasing angular speed:

| Motion condition | Point velocity | Tangential acceleration | Inward acceleration, while ω ≠ 0 | Angular velocity | Angular acceleration |
|---|---|---|---|---|---|
| Speeding up | Up in the plane | Up | Left toward the centre | Out of the plane | Out of the plane |
| Uniform rotation | Up in the plane | Zero | Left toward the centre | Out of the plane | Zero |
| Slowing down | Up in the plane | Down | Left toward the centre | Out of the plane | Into the plane |

Explain the invariants: angular and linear descriptions concern the same motion
at different descriptive levels; angular velocity and point velocity are not
components of one velocity. Tangential and inward accelerations are components
of one point's linear acceleration. Fixed-radius motion has zero radial velocity
but can have nonzero inward acceleration. Only after this distinction is secure
introduce a changed radius, another point, rotation reversal or a new viewpoint.
When the learner is confused, repair the earliest classification or arrow-meaning
gap before adding more formulas or branches. In standalone notes, include the
comparison's explanation and answer even if its prediction is a self-test.

### Connect the established quantities

Integrate the following into the explanation; a compact table can make the
relationships easier to compare:

| Element | What the student should be able to reconstruct |
|---|---|
| Physical meaning | What is described or measured, with scalar/vector status, units and reference frame/state |
| Mathematical dependence | Which quantities occur in the relation and which variables/parameters can vary in this model |
| Controlled comparison | How changing one quantity changes another when the stated others are fixed |
| Indirect influence | How forces, geometry, material state or constraints can change the variables even if absent from a definition |
| Information boundary | What the quantity/relation does not determine, and the extra information needed |
| Connection | Which earlier and later concepts or laws use this quantity, with links to their sections |

State proportionality, inverse dependence, powers or limiting behaviour where
they are meaningful. Explain the physical reason alongside the algebra.
Distinguish the relation's algebraic use from an intervention or causal claim:
rearranging a formula does not show what an unconstrained physical system will do.

### Implementation example: kinetic energy

For a nonrelativistic particle of positive mass m, measured in the stated
inertial frame, translational kinetic energy is K = ½mv², where v is speed.
For an extended body this is only its translational contribution unless rotation
and other motion have been accounted for separately.

| Comparison | Symbolic relationship | Physical interpretation |
|---|---|---|
| Fixed mass | K ∝ v² | Doubling speed quadruples kinetic energy |
| Fixed speed | K ∝ m | Doubling mass doubles kinetic energy |
| Fixed positive kinetic energy | v = √(2K/m) | A larger mass corresponds to a smaller speed under this imposed energy condition |
| Velocity reversed at the same speed | K unchanged | K carries no velocity-direction information |
| A different inertial frame | Recalculate v and K | K is frame-dependent |

Then expose the missing causal step: K = ½mv² alone does not determine how speed
changes when a real mass, force or initial state changes. At fixed net force,
acceleration depends on mass; at fixed net work, the kinetic-energy change is
specified; at fixed initial speed, the initial kinetic energy changes with mass.
Develop contrasting situations with those different controls.

Clarify dependencies absent from the definition. Force and elapsed time do not
appear explicitly in K = ½mv², but they may alter v through the dynamics. A
given K and m determine speed, not the signed velocity, trajectory, force history
or time taken. Give the dimensions kg·m²/s² and check K → 0 as v → 0.

## 3. Connect formulas by showing what each step contributes

For each major formula family, start from a definition or governing law already
introduced, state the assumptions, then develop the derived relations with enough
algebra to show the conceptual change. For each transition explain:

- **Starting information:** what the prior relation describes and supplies.
- **Operation or principle:** differentiation, integration, substitution,
  conservation, geometric projection, or a constraint.
- **Conditions:** when that operation/model is valid and what is held fixed.
- **New information and limits:** what the new relation makes accessible,
  what it compresses or loses, and when it is useful for solving a problem.

When useful, present a short equation chain, a small relation table or an
annotated diagram. Label every arrow with its mathematical operation or physical
law. Explain the relations in nearby prose and link to the full sections.

### Implementation example: Newton's law to the work–energy theorem

For a constant-mass particle in an inertial frame, begin with Fnet = ma. Take the
dot product with velocity and use a = dv/dt:

$$
\mathbf F_{\rm net}\cdot\mathbf v
=m\frac{d\mathbf v}{dt}\cdot\mathbf v
=\frac{d}{dt}\left(\frac12m|\mathbf v|^2\right).
$$

Define mechanical power delivered by a force as its dot product with velocity.
Since d r = v dt, integration over the motion gives:

$$
W_{\rm net}
=\int_1^2\mathbf F_{\rm net}\cdot d\mathbf r
=K_2-K_1.
$$

Spell out the connection: Newton's law describes instantaneous vector motion;
projecting along the velocity selects the part changing speed; integration
accumulates work between states. The energy theorem can find speed changes
without reconstructing the full force-time history. It does not, by itself,
specify a velocity direction or a unique time history. Force perpendicular to
velocity is a contrast case: direction can change while K is constant.

When the taught scope includes conservative forces, add the next justified
connection Wc = −ΔU. Splitting net work into conservative work plus remaining
work yields Δ(K+U) = Wother. Only when Wother = 0 in the selected system/model
does this reduce to conservation of mechanical energy. Keep each force's work
or its potential-energy contribution counted once.

## 4. Teach the quantity path used to solve a problem

For every major problem family, identify givens, target, unknown intermediate
quantities, constraints and applicable laws before inserting numbers. Work
backwards from the target to select the required relation, then show a forward
route from the givens to that target.

Attach an equation and its conditions to each arrow. Explain why the intermediate
quantity helps, where geometry/forces enter, and whether the available
information uniquely determines the target. If it is insufficient, identify
the missing condition or datum instead of silently adding one.

### Implementation example: height to speed, then a different target

A constant-mass particle starts from rest and descends a height h under uniform
gravity in a model with no other net work. Define h as a positive downward height
change and use a fixed inertial laboratory frame.

| Transition | Equation and justification |
|---|---|
| Height → gravitational energy change | ΔUg = −mgh, uniform gravity and a consistent vertical reference |
| Gravitational energy change → kinetic-energy change | ΔK = −ΔUg = mgh, no remaining work in the selected mechanical balance |
| Kinetic-energy change → final kinetic energy | Kf = mgh, because Ki = 0 |
| Final kinetic energy → speed | ½mv² = mgh, so v = √(2gh), for the particle model |

Follow the chain with interpretation: mass cancels because gravitational energy
release and translational inertia both scale with m in this model. Check dimensions
and the h → 0 limit. Speed is determined, while velocity direction needs the
motion geometry.

Change a physical condition to expose the chain's structure:

- With nonzero initial speed, Kf = Ki+mgh and v² = v0²+2gh.
- With sliding friction, calculate its work and use Δ(K+U) = Wfriction.
- With a massive rotating pulley, include rotational kinetic energy and the
  no-slip relation before solving for speed.

If the new target is tension, normal reaction or contact feasibility, show why
the endpoint energy equation is insufficient. Recover the required acceleration
or force relation from Newton's law, the geometry and any torque/constraint
equations. Compare methods on a worked case; do not infer constant acceleration
merely because an energy equation supplied endpoint speeds.

## 5. Validate the relationships, not just the arithmetic

Before delivering a detailed physics topic, check that:

- Before its use, each central quantity has a selected object, descriptive
  level, physical meaning, units/reference and an explanation of any arrows.
- The prose identifies each important connection's relationship type and
  distinguishes components of one quantity from different descriptions of motion.
- Each quantity has explicit dependencies, a controlled comparison and an
  information boundary; the comparison explains both changes and invariants.
- Each major formula family has an explained connection to definitions/laws
  and to the neighbouring concepts actually used in the topic.
- Representative worked problems show givens → intermediates → target, with
  equations and model conditions at the transitions.
- Contrasting examples change a meaningful constraint and explain how the
  quantity path or formula choice changes.
- The native contents, section links, equations and relationship tables survive
  publication/readback. Quantity paths in the rapid review point back to these
  detailed explanations.

Review representative sections from a novice's perspective using only the saved
notes: can the reader identify what is described, interpret its representation,
name the connection to prior concepts, state its conditions and reconstruct a
prediction after one condition changes? Locate the actual explanatory passages
and the worked contrast that support those answers. Resolve gaps in the body;
the presence of headings, formulas, diagrams or quiz answers is not by itself
evidence of explanatory completeness. This authoring check does not require live
student responses and does not establish mastery.

Judge completeness against the declared course level and source scope, rather
than a word count or an exhaustive graph of every conceivable relation. Keep
the learner's mastery separate from the presence of the explanations.
