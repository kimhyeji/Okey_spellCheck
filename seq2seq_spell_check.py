
import math
import tensorflow as tf
import tensorflow.contrib.seq2seq as seq2seq
from tensorflow.contrib.rnn import LSTMCell, LSTMStateTuple


file_name = 'C:/Users/kimhyeji/PycharmProjects/tfTest/dic_modify.csv'
graph_dir = 'C:/Users/kimhyeji/PycharmProjects/tfTest/tmp/test_logs'
save_dir = 'C:/Users/kimhyeji/PycharmProjects/tfTest/tmp/checkpoint'
class SmallConfig():
    """
    적은 학습 데이터에서의 하이퍼 파라미터
    """

    batch_size = 20
    syllable_size = 11224
    hidden_size = 200
    len_max = 7
    data_size = 35228

    #1에폭 당 배치의 개수
    max_batches = int(data_size/batch_size)

    #배치 당 출력
    batch_print = 1000

    #에폭 수
    epoch = 1

config = SmallConfig()

class Seq2SeqModel():
    """Seq2Seq model usign blocks from new `tf.contrib.seq2seq`.
    Requires TF 1.0.0-alpha"""

    PAD = 0
    EOS = 1

    def __init__(self, encoder_cell, decoder_cell, vocab_size, embedding_size,
                 bidirectional=True,
                 attention=False,
                 debug=False):
        self.debug = debug
        self.bidirectional = bidirectional
        self.attention = attention

        self.encoder_cell = encoder_cell
        self.decoder_cell = decoder_cell

        self.max_batches = config.max_batches
        self.batch_print = config.batch_print

        self.vocab_size = config.syllable_size
        self.embedding_size = config.hidden_size
        self.batch_size = config.batch_size
        self.len_max = config.len_max
        self.data_size = config.data_size
        self.epoch = config.epoch
        self._make_graph()

    @property
    def decoder_hidden_units(self):
        return self.decoder_cell.output_size

    def _make_graph(self):
        if self.debug:
            self._init_debug_inputs()
        else:
            self._init_placeholders()

        self._init_decoder_train_connectors()
        self._init_embeddings()

        if self.bidirectional:
            self._init_bidirectional_encoder()
        else:
            self._init_simple_encoder()

        self._init_decoder()

        self._init_optimizer()

    def _init_placeholders(self):
        """ Everything is time-major """

        self.encoder_inputs_length = tf.placeholder(
            shape=(None,),
            dtype=tf.int32,
            name='encoder_inputs_length',
        )
        self.decoder_targets_length = tf.placeholder(
        shape = (None,),
        dtype = tf.int32,
        name = 'decoder_targets_length',
        )
        self.encoder_inputs = tf.placeholder(
            shape=(None, None),
            dtype=tf.int32,
            name='encoder_inputs',
        )
        self.decoder_targets = tf.placeholder(
            shape=(None, None),
            dtype=tf.int32,
            name='decoder_targets'
        )


    def _init_decoder_train_connectors(self):
        """
        During training, `decoder_targets`
        and decoder logits. This means that their shapes should be compatible.
        Here we do a bit of plumbing to set this up.
        """
        with tf.name_scope('DecoderTrainFeeds'):
            sequence_size, batch_size = tf.unstack(tf.shape(self.decoder_targets))

           # EOS_SLICE = tf.ones([1, batch_size], dtype=tf.int32) * self.EOS
            PAD_SLICE = tf.ones([1, batch_size], dtype=tf.int32) * self.PAD

            #decoder_input= <EOS> + decoder_targets
            self.decoder_train_inputs = tf.concat([PAD_SLICE, self.decoder_targets], axis=0)
            self.decoder_train_length = self.decoder_targets_length

            #decoder_targets의 길이를 encoder_inputs과 맞추기 위해
            #batch 내의 최대 길이를 찾아서 decoder_targets로 맞춰줌
            b_s = tf.constant(self.batch_size, dtype=tf.int64)
            self.max_targets_len = tf.stack([tf.to_int64(tf.reduce_max(self.decoder_targets_length)),b_s])
            begin = tf.constant([0,0], dtype = tf.int64)

            #decoder_targets = decoder_targets + <PAD>
            self.decoder_train_targets = tf.slice(self.decoder_targets, begin, self.max_targets_len)

            # decoder 가중치 초기화
            with tf.name_scope('DecoderTrainFeeds'):
                self.loss_weights = tf.ones([
                    self.batch_size,
                    tf.reduce_max(self.decoder_targets_length)
                ], dtype=tf.float32, name="loss_weights")

    def _init_embeddings(self):
        """
        음운의 embedding
        초기화 설정방법을 생각해봐야함
        """
        with tf.variable_scope("embedding") as scope:

            # Uniform(-sqrt(3), sqrt(3)) has variance=1.
            sqrt3 = math.sqrt(3)
            initializer = tf.random_uniform_initializer(-sqrt3, sqrt3)

            self.embedding_matrix = tf.get_variable(
                name="embedding_matrix",
                shape=[self.vocab_size, self.embedding_size],
                initializer=initializer,
                dtype=tf.float32)

            self.encoder_inputs_embedded = tf.nn.embedding_lookup(
                self.embedding_matrix, self.encoder_inputs)

            self.decoder_train_inputs_embedded = tf.nn.embedding_lookup(
                self.embedding_matrix, self.decoder_train_inputs)

    def _init_simple_encoder(self):
        with tf.variable_scope("Encoder") as scope:
            (self.encoder_outputs, self.encoder_state) = (
                tf.nn.dynamic_rnn(cell=self.encoder_cell,
                                  inputs=self.encoder_inputs_embedded,
                                  sequence_length=self.encoder_inputs_length,
                                  time_major=True,
                                  dtype=tf.float32)
                )

    def _init_bidirectional_encoder(self):
        """
        input을 뒤집어서 한번 더 학습시킨다.
        """
        with tf.variable_scope("BidirectionalEncoder") as scope:

            ((encoder_fw_outputs,
              encoder_bw_outputs),
             (encoder_fw_state,
              encoder_bw_state)) = (
                tf.nn.bidirectional_dynamic_rnn(cell_fw=self.encoder_cell,
                                                cell_bw=self.encoder_cell,
                                                inputs=self.encoder_inputs_embedded,
                                                sequence_length=self.encoder_inputs_length,
                                                time_major=True,
                                                dtype=tf.float32)
                )

            self.encoder_outputs = tf.concat((encoder_fw_outputs, encoder_bw_outputs), 2)

            if isinstance(encoder_fw_state, LSTMStateTuple):

                encoder_state_c = tf.concat(
                    (encoder_fw_state.c, encoder_bw_state.c), 1, name='bidirectional_concat_c')
                encoder_state_h = tf.concat(
                    (encoder_fw_state.h, encoder_bw_state.h), 1, name='bidirectional_concat_h')
                self.encoder_state = LSTMStateTuple(c=encoder_state_c, h=encoder_state_h)

            elif isinstance(encoder_fw_state, tf.Tensor):
                self.encoder_state = tf.concat((encoder_fw_state, encoder_bw_state), 1, name='bidirectional_concat')

    def _init_decoder(self):
        """
            decoder cell.
            attention적용/비적용 경우.
            두개를 비교해야함
        """
        with tf.variable_scope("Decoder") as scope:
            def output_fn(outputs):
                return tf.contrib.layers.linear(outputs, self.vocab_size, scope=scope)

            if not self.attention:
                decoder_fn_train = seq2seq.simple_decoder_fn_train(encoder_state=self.encoder_state)
                decoder_fn_inference = seq2seq.simple_decoder_fn_inference(
                    output_fn=output_fn,
                    encoder_state=self.encoder_state,
                    embeddings=self.embedding_matrix,
                    start_of_sequence_id=self.EOS,
                    end_of_sequence_id=self.EOS,
                    maximum_length=tf.reduce_max(self.encoder_inputs_length) + 3,
                    num_decoder_symbols=self.vocab_size,
                )
            else:

                # attention_states: size [batch_size, max_time, num_units]
                attention_states = tf.transpose(self.encoder_outputs, [1, 0, 2])

                (attention_keys,
                attention_values,
                attention_score_fn,
                attention_construct_fn) = seq2seq.prepare_attention(
                    attention_states=attention_states,
                    attention_option="bahdanau",
                    num_units=self.decoder_hidden_units,
                )

                decoder_fn_train = seq2seq.attention_decoder_fn_train(
                    encoder_state=self.encoder_state,
                    attention_keys=attention_keys,
                    attention_values=attention_values,
                    attention_score_fn=attention_score_fn,
                    attention_construct_fn=attention_construct_fn,
                    name='attention_decoder'
                )

                decoder_fn_inference = seq2seq.attention_decoder_fn_inference(
                    output_fn=output_fn,
                    encoder_state=self.encoder_state,
                    attention_keys=attention_keys,
                    attention_values=attention_values,
                    attention_score_fn=attention_score_fn,
                    attention_construct_fn=attention_construct_fn,
                    embeddings=self.embedding_matrix,
                    start_of_sequence_id=self.EOS,
                    end_of_sequence_id=self.EOS,
                    maximum_length=tf.reduce_max(self.encoder_inputs_length) + 3,
                    num_decoder_symbols=self.vocab_size,
                )

            (self.decoder_outputs_train,
             self.decoder_state_train,
             self.decoder_context_state_train) = (
                seq2seq.dynamic_rnn_decoder(
                    cell=self.decoder_cell,
                    decoder_fn=decoder_fn_train,
                    inputs=self.decoder_train_inputs_embedded,
                    sequence_length=self.decoder_train_length,
                    time_major=True,
                    scope=scope,
                )
            )

            self.decoder_logits_train = output_fn(self.decoder_outputs_train)
            self.decoder_prediction_train = tf.argmax(self.decoder_logits_train, axis=-1, name='decoder_prediction_train')

            scope.reuse_variables()

            (self.decoder_logits_inference,
             self.decoder_state_inference,
             self.decoder_context_state_inference) = (
                seq2seq.dynamic_rnn_decoder(
                    cell=self.decoder_cell,
                    decoder_fn=decoder_fn_inference,
                    time_major=True,
                    scope=scope,
                )
            )
            self.decoder_prediction_inference = tf.argmax(self.decoder_logits_inference, axis=-1, name='decoder_prediction_inference')

    def _init_optimizer(self):

        ##################### 고쳐야할 부분. transpose 가 필요가 없다.###############
        logits = tf.transpose(self.decoder_logits_train, [1, 0, 2])
        targets = tf.transpose(self.decoder_train_targets, [1, 0])

        #손실함수
        self.loss = seq2seq.sequence_loss(logits=logits, targets=targets,
                                          weights=self.loss_weights)
        #Optimizer를 변경해보는 시도도 필요함
        self.train_op = tf.train.AdamOptimizer().minimize(self.loss)

    def make_train_inputs(self, inputs_length_, targets_length_, inputs_, targets_ ):
        """
                feed_dict에 입력할 형태
                test 용
        """
        return {
            self.encoder_inputs_length: inputs_length_,
            self.decoder_targets_length: targets_length_,
            self.encoder_inputs: inputs_,
            self.decoder_targets: targets_,
        }

    def make_inference_inputs(self, inputs_length_, inputs_):
        """
                feed_dict에 입력할 형태
                inference 용
        """
        return {
            self.encoder_inputs: inputs_,
            self.encoder_inputs_length: inputs_length_,
        }

    def read_data(self, file_name):
        """
        오류단어길이, 목표단어길이, 오류단어, 목표단어 형식의
        csv 데이터를 읽어온다.
        단어는 각 글자를 숫자로 바꿔 저장했다.
        """

        csv_file = tf.train.string_input_producer([file_name], name='file_name')
        reader = tf.TextLineReader()
        _, line = reader.read(csv_file)
        record_defaults = [[1] for _ in range(self.len_max * 2 + 2)]
        #decode_csv는 정해진 형식(record_defaults)만 받아올 수 있기 때문에 미리 padding이 이뤄진 데이터를 준비했다.
        data = tf.decode_csv(line, record_defaults=record_defaults, field_delim=',')

        #각 데이터를 분리한다.
        #slice(분할할 데이터, 시작위치, 사이즈)
        len_error = tf.slice(data, [0], [1])
        len_target = tf.slice(data, [1], [1])
        error = tf.slice(data, [2], [self.len_max])
        target = tf.slice(data, [2 + self.len_max], [self.len_max])

        return len_error, len_target, error, target

    def read_data_batch(self,file_name):
        """
            배치로 나눠 반환한다.
        """
        len_x, len_y, x, y = self.read_data(file_name)

        #session 단계에서 queue를 생성해줘야 한다.
        batch_len_x, batch_len_y, batch_x, batch_y = tf.train.batch([len_x,len_y,x,y], dynamic_pad = True, batch_size = self.batch_size)

        ############고쳐야하는 부분. 전체적인 형태를 transpose 없이 고쳐야함#################
        batch_len_x = tf.reshape(batch_len_x,[-1])
        batch_len_y = tf.reshape(batch_len_y,[-1])
        batch_x = tf.transpose(batch_x)
        batch_y = tf.transpose(batch_y)

        return batch_len_x, batch_len_y, batch_x, batch_y


def make_seq2seq_model(**kwargs):
    args = dict(encoder_cell=LSTMCell(10),
                decoder_cell=LSTMCell(20),
                attention=True,
                bidirectional=True)
    args.update(kwargs)
    return Seq2SeqModel(**args)


def train_on_copy_task_(session, model,
                        len_x,len_y,x,y,
                        initial_step = 0,
                       verbose=True):
    """
            학습을 실행하는 함수
    """
    loss_track = []
    for epoch in range(initial_step,model.epoch):
        for batch in range(model.max_batches + 1):
            b_len_x, b_len_y, b_x, b_y = session.run([len_x, len_y, x, y])

            fd = model.make_train_inputs(b_len_x, b_len_y, b_x, b_y)
            _ = session.run(model.max_targets_len, fd)
            _, l = session.run([model.train_op, model.loss], fd)
            loss_track.append(l)

            if verbose:
                if batch == 0 or batch % model.batch_print == 0:
                    #그래프 출력
                    summary = session.run(merged, feed_dict=fd)
                    writer.add_summary(summary, batch*(epoch+1))

                    print('batch {}'.format(batch))
                    print('  minibatch loss: {}'.format(session.run(model.loss, fd)))
                    for i, (e_in, dt_pred) in enumerate(zip(
                            fd[model.encoder_inputs].T,
                            session.run(model.decoder_prediction_train, fd).T
                    )):
                        print('  sample {}:'.format(i + 1))
                        print('    enc input           > {}'.format(e_in))
                        print('    dec train predicted > {}'.format(dt_pred))
                        if i >= 2:
                            break
                    print()

        #1에폭마다 저장한다.
        saver.save(session, save_dir+'.ckpt', global_step = epoch)
    return loss_track



tf.reset_default_graph()
tf.set_random_seed(1)
model = Seq2SeqModel(encoder_cell=LSTMCell(10),
                         decoder_cell=LSTMCell(20),
                         vocab_size=12000,
                         embedding_size=200,
                         attention=True,
                         bidirectional=True,
                         debug=False)
b_len_x, b_len_y, b_x, b_y = model.read_data_batch(file_name)

#tensorboard에 graph 출력을 위해
tf.summary.scalar('cost',model.loss)

with tf.Session() as session:
    merged = tf.summary.merge_all()
    writer = tf.summary.FileWriter(graph_dir, session.graph)

    saver = tf.train.Saver()
    initial_step = 0
    ckpt = tf.train.get_checkpoint_state(save_dir)

    #checkpoint가 존재할 경우 변수 값을 복구한다.
    if ckpt and ckpt.model_checkpoint_path:
        saver.restore(session, ckpt.model_checkpoint_path)
        #복구한 시작 지점
        initial_step = int(ckpt.model_checkpoint_path.rsplit('-', 1)[1])
        print(initial_step)

    try:
        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(sess=session, coord=coord)

        session.run(tf.global_variables_initializer())
        train_on_copy_task_(session, model,
                           b_len_x, b_len_y, b_x, b_y,
                           initial_step,
                           verbose=True)


    except tf.errors.OutOfRangeError as e:
        print("X(")


"""
tf.reset_default_graph()
        with tf.Session() as session:
            model = make_seq2seq_model()
            session.run(tf.global_variables_initializer())
            fd = model.make_inference_inputs([[5, 4, 6, 7], [6, 6]])
            inf_out = session.run(model.decoder_prediction_inference, fd)
            print(inf_out)
"""