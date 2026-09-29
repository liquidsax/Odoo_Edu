# 在服务运行状态下就地升级 tutoring_center（等价于后台"应用"页点"升级"）
module = env['ir.module.module'].search([('name', '=', 'tutoring_center')])
print('state before:', module.state)
assert module.state == 'installed', 'unexpected state'
module.button_immediate_upgrade()
env.cr.commit()
print('state after:', module.state)
print('knowledge point model:', bool(env['ir.model'].search([('model', '=', 'tutoring.knowledge.point')])))
print('student point model:', bool(env['ir.model'].search([('model', '=', 'tutoring.student.point')])))
print('point menu view:', bool(env.ref('tutoring_center.view_tutoring_knowledge_point_list', raise_if_not_found=False)))
